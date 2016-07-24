import numpy as np
import helpers as h

__author__ = "Shaun Howard (smh150@case.edu)"


def ik_soln_exists(goal_pose, kin):
    """
    Determines if an IK solution exists for the goal_pose using the provided kinematics solver instance, kin.
    :param goal_pose: the goal pose to determine if a soln exists for
    :param kin: the kinematics solver instance
    :return: whether a soln exists and the angles for that soln as a numpy array
    """
    goal_angles = None
    if goal_pose is not None:
        goal_angles = None
        if goal_pose:
            goal_angles = kin.solve(position=goal_pose.position, orientation=goal_pose.orientation)
    if goal_angles is not None:
        return True, goal_angles
    else:
        return False, None


class RRT:
    """
    Class for Shaun Howard's online hybrid RRT-JT/Random IK joint angle planner.
    """

    def __init__(self, q_start, p_goal, kin_solver, side, joint_names, obstacles, exec_angles_method):
        """
        Constructor for RRT. Accepts a numpy array of starting angles, probability to approach the goal in a straight
        line, the kinematics solver instance for the RRT side arm, an ordered list of joint_names from base to end
        effector, a list of obstacle points that should not include the current arm being planned for, and the method to
        execute the joint angles from the Merry object instance used to create this RRT instance.
        :param q_start: 7x1 numpy vector of starting joint angles
        :param p_goal: probability to approach goal with random straight-line IK goal planner
        :param kin_solver: the KDL kinematics solver instance
        :param side: the side, left or right, of arm to plan for
        :param joint_names: the ordered list of joint names from base to end effector
        :param obstacles: the list of obstacles not including the arm being planned for
        :param exec_angles_method: the method to execute the joint angles on Merry
        """
        self.kin = kin_solver
        self.q_start = q_start
        self.update_goal(p_goal)
        self.nodes = []
        self.side = side
        # note: obstacles should be and are assumed to be sorted by distance from base link
        self.obstacles = obstacles
        self.joint_names = joint_names
        self.exec_angles_method = exec_angles_method

        # define goals
        self.x_goal = None
        self.p_goal = None

    def add_nodes(self, nodes_to_add):
        self.nodes.extend(nodes_to_add)

    def curr_node(self):
        if len(self.nodes) == 0:
            return self.q_start
        return self.nodes[-1]

    def goal_pose(self):
        return self.p_goal

    def goal_node(self):
        return self.x_goal

    def goal_point(self):
        return self.goal_node()[:3]

    def dist(self, start, stop):
        return np.linalg.norm(stop - start)

    def _dist_to_goal(self, curr):
        return self.dist(curr, self.goal_node())

    def dist_to_goal(self):
        return self._dist_to_goal(self.fwd_kin(self.curr_node()))

    def closest_node_to_goal(self):
        return self.curr_node()

    def workspace_delta(self, x_curr):
        return (self.x_goal - x_curr)[:6]

    def fwd_kin(self, q_list):
        return self.kin.solve_fwd_kin(q_list)

    def joint_fwd_kin(self, q_list, end_link):
        return self.kin.joint_fwd_kin(q_list, "base", end_link)

    def fwd_kin_all(self, q_list):
        return self.kin.fwd_kin_all(q_list)

    def update_obstacles(self, new_obs):
        # note: obstacles should be and are assumed to be sorted by distance from base link
        self.obstacles = np.mat(new_obs)

    def update_goal(self, p_goal):
        self.x_goal = h.pose_to_7x1_vector(p_goal)
        self.p_goal = p_goal
        print "updating rrt goal"

    def _check_collision(self, x_3x1, avoidance_radius):
        """
        Determines if the 3x1 point vector provided collides with any obstacles within the specified
        avoidance radius.
        :param x_3x1: the 3x1 numpy point vector containin x,y,z
        :param avoidance_radius: the radius in meters to avoid obstacles around point with
        :return: True if no collisions of 3x1 point, False otherwise
        """
        if len(self.obstacles) > 1:
            for obs_point in self.obstacles[:]:
                dist = np.linalg.norm(obs_point - x_3x1)
                if dist < avoidance_radius:
                    # any obstacles outside of avoidance radius of robot since obstacles are sorted by distance
                    return False
        return True

    def _check_collisions(self, link_pose_mat, avoidance_radius):
        """
        Determines if any of the arm links will intersect with objects within the provided
        avoidance radius (in meters). Returns True if there are no collisions along the specified arm link positions,
        returns False otherwise.
        :param link_pose_mat: the matrix of 3x1 point vectors of an arm on the robot
        :param avoidance_radius: the radius in meters to avoid obstacles within around the arm links
        :return: True if there are no collisions, False otherwise
        """
        for link_pose in link_pose_mat:
            # only use x,y,z from link pose
            x_3x1 = np.array((link_pose[0, 0], link_pose[0, 1], link_pose[0, 2]))
            if not self._check_collision(x_3x1, avoidance_radius):
                return False
        return True

    def collision_free(self, q_new_angles, avoidance_radius=0.2):
        """
        Determines if the provided vector of new angles are collision free around the given
        avoidance radius.
        :param q_new_angles: the 7x1 numpy vector of angles to check for collision, ordered from base to end effector
        :param avoidance_radius: the obstacle avoidance radius in meters
        :return: whether the arm will collide with obstacles when going to the specified q_new_angles
        """
        # get the poses of all links in the arm
        # only take from the second on since the first two are always the same at 0,0,0
        link_pose_matrix = self.fwd_kin_all(q_new_angles)
        selected_collision_end_links = link_pose_matrix[len(link_pose_matrix)-4:]
        # check collisions for each link in the arm
        return self._check_collisions(selected_collision_end_links, avoidance_radius)

    def exec_angles(self, q):
        """
        Moves to the specified joint angles, q.
        :param q: a 7x1 vector of joint angles to approach
        :return: the status of the operation, 0 for success, 1 for error
        """
        q_dict = dict()
        curr = 0
        for n in self.joint_names:
            q_dict[n] = q[curr]
            curr += 1
        return self.exec_angles_method(q_dict, self.side)

    def extend_toward_goal(self, dist_thresh=0.02):
        """
        Uses the an online hybrid jacobian transpose RRT planning step to approach the goal
        to the provided distance threshold. Adds nodes to the RRT tree as valid solution nodes are found.
        :param dist_thresh: the distance from the goal considered tolerable as reaching the goal pose
        """
        # get the closest node to goal and try to complete the tree
        q_old = self.closest_node_to_goal()
        first = True
        Q_new = []
        prev_dist_to_goal = self.dist_to_goal()
        while first or prev_dist_to_goal > dist_thresh:
            print "looking for jacobian soln..."
            if first:
                first = False
            J_T = self.kin.jacobian_transpose(q_old)
            x_old = self.fwd_kin(q_old)
            d_x = self.workspace_delta(x_old)
            d_q = np.dot(J_T, d_x).tolist()
            d_q = np.array(d_q[0])
            q_new = q_old + d_q
            curr_dist_to_goal = self._dist_to_goal(self.fwd_kin(q_new))
            if curr_dist_to_goal < prev_dist_to_goal and self.collision_free(q_new):
                print "jacobian goal step: curr dist to goal: " + str(curr_dist_to_goal)
                self.exec_angles(q_new)
                Q_new.append(q_new)
                q_old = q_new
                prev_dist_to_goal = curr_dist_to_goal
            else:
                print "jac: could not find collision-free soln"
                break
        self.add_nodes(Q_new)

    def ik_extend_randomly(self, curr_pos, dist_thresh, offset=0.1, avoidance_radius=0.2, num_tries=5):
        """
        Random straight-line extension using KDL IK planner for the RRT step.
        Starts generating random points close to goal, from the goal out, until it finds a valid solution.
        Adds the successful and valid step nodes to the RRT.
        :param curr_pos: the 3x1 current position of the end effector
        :param dist_thresh: the distance threshold considered tolerable for reaching the goal state
        :param offset: the cartesian step offset upper limit of the range at which to generate points, starting from
        the goal and stepping out the range until a valid soln is found within that range.
        :param avoidance_radius: the radius to avoid collisions around the arm being planner for
        :param num_tries: the number of times to regenerate a new random point at a larger step away from goal
        than the previous try with step being offset
        """
        # TODO modify to start randomly near goal then move away from goal if no solns present
        # returns the nearest distance to goal from the last node added by this method
        # only add one node via random soln for now
        # first = True
        Q_new = []
        prev_dist_to_goal = self.dist_to_goal()
        num_tries_left = num_tries
        first = True
        # start with soln at goal and work outward until soln available
        curr_diameter = 0
        while prev_dist_to_goal > dist_thresh and num_tries_left > 0:
            goal_pose = self.goal_pose()
            if first:
                first = False
                # first, try the goal point
                next_point = self.goal_point()
            else:
                goal_arr = self.goal_node()
                next_point = []
                for i in range(3):
                    curr_coord = curr_pos[i]
                    goal_coord = goal_arr[i]
                    radius = curr_diameter/2.0
                    next_point.append(h.generate_random_decimal(curr_coord - radius, goal_coord + radius))
                    # if curr_coord < goal_coord:
                    #     next_point.append(h.generate_random_decimal(curr_coord-offset, goal_coord+offset))
                    # else:
                    #     next_point.append(h.generate_random_decimal(goal_coord-offset, curr_coord+offset))
            print "looking for ik soln..."
            if self._check_collision(next_point, avoidance_radius):
                next_pose = h.generate_goal_pose_w_same_orientation(next_point, goal_pose.orientation)
                solved, q_new = ik_soln_exists(next_pose, self.kin)
                if solved:
                    curr_dist_to_goal = self._dist_to_goal(self.fwd_kin(q_new))
                    curr_pos = next_point
                    # only add the point as a soln if the distance from this point to goal is less than that from the
                    # last end effector point
                    if curr_dist_to_goal < prev_dist_to_goal and self.collision_free(q_new):
                        print "random ik planner: curr dist to goal: " + str(curr_dist_to_goal)
                        self.exec_angles(q_new)
                        Q_new.append(q_new)
                        prev_dist_to_goal = curr_dist_to_goal
                        continue
                    else:
                        print "ik: soln not collision free..."
                else:
                    print "could not find ik soln for generated point"
            # increment current range for generating random points by adding another offset amount
            curr_diameter += offset
            num_tries_left -= 1
        self.add_nodes(Q_new)
