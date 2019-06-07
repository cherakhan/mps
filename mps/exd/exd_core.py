"""
  Harness for Blackbox Experiment Designn. Implements a parent class that can be inherited
  by all methods for black-box optimisation.
  -- kandasamy@cs.cmu.edu
"""

# pylint: disable=import-error
# pylint: disable=no-member
# pylint: disable=invalid-name
# pylint: disable=super-on-old-class
# pylint: disable=abstract-class-not-used

from argparse import Namespace
import time
import numpy as np

# Local imports
from exd.exd_utils import EVAL_ERROR_CODE
from utils.option_handler import get_option_specs
from utils.reporters import get_reporter

ed_core_args = [
  get_option_specs('max_num_steps', False, 1e7,
    'If exceeds this many evaluations, stop.'),
  get_option_specs('capital_type', False, 'return_value',
    'Should be one of return_value, cputime, or realtime'),
  get_option_specs('mode', False, 'asy',
    'If \'syn\', uses synchronous parallelisation, else asynchronous.'),
  get_option_specs('build_new_model_every', False, 17,
    'Updates the model via a suitable procedure every this many iterations.'),
  get_option_specs('report_results_every', False, 1,
    'Report results every this many iterations.'),
  # Initialisation
  get_option_specs('init_capital', False, None,
    ('The capital to be used for initialisation.')),
  get_option_specs('init_capital_frac', False, None,
    ('The fraction of the total capital to be used for initialisation.')),
  get_option_specs('num_init_evals', False, 20,
    ('The number of evaluations for initialisation. If <0, will use default.')),
  # The amount of effort we will use for initialisation is prioritised by init_capital,
  # init_capital_frac and num_init_evals.
  get_option_specs('prev_evaluations', False, None,
    'Data for any previous evaluations.'),
  get_option_specs('get_initial_qinfos', False, None,
    'A function to obtain initial qinfos.'),
  get_option_specs('init_method', False, 'rand',
    'Method to obtain initial queries. Is used if get_initial_qinfos is None.'),
  ]

mf_ed_args = [
  get_option_specs('fidel_init_method', False, 'rand',
    'Method to obtain initial fidels. Is used if get_initial_qinfos is None.'),
  get_option_specs('init_set_to_fidel_to_opt_with_prob', False, 0.25,
    'Method to obtain initial fidels. Is used if get_initial_qinfos is None.'),
  ]

class ExperimentDesigner(object):
  """ BlackboxExperimenter Class. """
  #pylint: disable=attribute-defined-outside-init
  #pylint: disable=too-many-instance-attributes

  # Methods needed for construction -------------------------------------------------
  def __init__(self, experiment_caller, worker_manager, model=None,
               options=None, reporter=None):
    """ Constructor.
        experiment_caller is an ExperimentCaller instance.
        worker_manager is a WorkerManager instance.
    """
    # Set up attributes.
    self.experiment_caller = experiment_caller
    self.domain = experiment_caller.domain
    self.worker_manager = worker_manager
    self.options = options
    self.reporter = get_reporter(reporter)
    self.model = model
    # Other set up
    self._set_up()

  def _set_up(self):
    """ Some additional set up routines. """
    # Set up some book keeping parameters
    self.available_capital = 0.0
    self.num_completed_evals = 0
    self.step_idx = 0
    self.num_succ_queries = 0
    # Initialise worker manager
    self.worker_manager.set_experiment_designer(self)
    copyable_params_from_worker_manager = ['num_workers']
    for param in copyable_params_from_worker_manager:
      setattr(self, param, getattr(self.worker_manager, param))
    # Other book keeping stuff
    self.last_report_at = 0
    self.last_model_build_at = 0
    self.eval_points_in_progress = []
    self.eval_idxs_in_progress = []
    # Set initial history
    # query infos will maintain a list of namespaces which contain information about
    # the query in send order. Everything else will be saved in receive order.
    self.history = Namespace(query_step_idxs=[],
                             query_points=[],
                             query_vals=[],
                             query_true_vals=[],
                             query_send_times=[],
                             query_receive_times=[],
                             query_eval_times=[],
                             query_worker_ids=[],
                             query_qinfos=[],
                             job_idxs_of_workers={k:[] for k in
                                                  self.worker_manager.worker_ids},
                            )
    self.to_copy_from_qinfo_to_history = {
      'step_idx': 'query_step_idxs',
      'point': 'query_points',
      'val': 'query_vals',
      'true_val': 'query_true_vals',
      'send_time': 'query_send_times',
      'receive_time': 'query_receive_times',
      'eval_time': 'query_eval_times',
      'worker_id': 'query_worker_ids',
      }
    # Post child set up.
    policy_prefix = 'asy' if self.is_asynchronous() else 'syn'
    self.full_policy_name = policy_prefix + '-' + self._get_policy_str() + '-' + \
                            self._get_problem_str()
    self.history.full_policy_name = self.full_policy_name
    # Set pre_eval_points and results
    self.prev_eval_points = []
    self.prev_eval_vals = []
    # Multi-fidelity Set up
    if self.is_an_mf_policy() or self.experiment_caller.is_mf():
      self._mf_set_up()
    # Finally call the child set up.
    self._problem_set_up()
    self._policy_set_up()

  def _mf_set_up(self):
    """ Multi-fidelity set up. """
    assert self.experiment_caller.is_mf()
    self.fidel_space = self.experiment_caller.fidel_space
    # Set up history
    self.history.query_fidels = []
    self.history.query_cost_at_fidels = []
    self.to_copy_from_qinfo_to_history['fidel'] = 'query_fidels'
    self.to_copy_from_qinfo_to_history['cost_at_fidel'] = 'query_cost_at_fidels'
    # Set up previous evaluations
    self.prev_eval_fidels = []

  def _problem_set_up(self):
    """ Set up for a child class of Blackbox Experiment designer which describes the
        problem. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def _policy_set_up(self):
    """ Set up for a child class of Blackbox Experiment designer which describes the
        policy. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def _get_problem_str(self):
    """ Return a string describing the problem. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def _get_policy_str(self):
    """ Return a string describing the policy. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def is_asynchronous(self):
    """ Returns true if asynchronous."""
    return self.options.mode.lower().startswith('asy')

  def is_an_mf_policy(self):
    """ Returns True if the policy is a multi-fidelity policy. """
    raise NotImplementedError('Implement in a policy implementation.')

  # Book-keeping -------------------------------------------------------------
  def _update_history(self, qinfo):
    """ qinfo is a namespace information about the query. """
    # Update the number of jobs done by each worker regardless
    self.history.job_idxs_of_workers[qinfo.worker_id].append(qinfo.step_idx)
    self.history.query_qinfos.append(qinfo) # Save the qinfo
    # Now store in history
    for qinfo_name, history_name in self.to_copy_from_qinfo_to_history.iteritems():
      attr_list = getattr(self.history, history_name)
      attr_list.append(getattr(qinfo, qinfo_name))
    # Do any child update
    self._problem_update_history(qinfo)
    self._policy_update_history(qinfo)
    # Check for unsuccessful queries
    if qinfo.val != EVAL_ERROR_CODE:
      self.num_succ_queries += 1

  def _problem_update_history(self, qinfo):
    """ Any updates to history from the problem class. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def _policy_update_history(self, qinfo):
    """ Any updates to history from the policy class. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def _get_jobs_for_each_worker(self):
    """ Returns the number of jobs for each worker as a list. """
    jobs_each_worker = [len(elem) for elem in self.history.job_idxs_of_workers.values()]
    if self.num_workers <= 5:
      jobs_each_worker_str = str(jobs_each_worker)
    else:
      return '[min:%d, max:%d]'%(min(jobs_each_worker), max(jobs_each_worker))
    return  jobs_each_worker_str

  def _get_curr_job_idxs_in_progress(self):
    """ Returns the current job indices in progress. """
    if self.num_workers <= 4:
      return str(self.eval_idxs_in_progress)
    else:
      total_in_progress = len(self.eval_idxs_in_progress)
      min_idx = (-1 if total_in_progress == 0 else min(self.eval_idxs_in_progress))
      max_idx = (-1 if total_in_progress == 0 else max(self.eval_idxs_in_progress))
      dif = -1 if total_in_progress == 0 else max_idx - min_idx
      return '[min:%d, max:%d, dif:%d, tot:%d]'%(min_idx, max_idx, dif, total_in_progress)

  def _report_curr_results(self):
    """ Writes current result to reporter. """
    cap_frac = (np.nan if self.available_capital <= 0 else
                self.get_curr_spent_capital()/self.available_capital)
    report_str = ' '.join(['%s'%(self.full_policy_name),
                           '(%03d/%03d)'%(self.num_succ_queries, self.step_idx),
                           'cap: %0.3f:: '%(cap_frac),
                           self._get_problem_report_results_str(),
                           self._get_policy_report_results_str(),
                           'w=%s,'%(self._get_jobs_for_each_worker()),
                           'inP=%s'%(self._get_curr_job_idxs_in_progress()),
                          ])
    self.reporter.writeln(report_str)
    self.last_report_at = self.step_idx

  def _get_problem_report_results_str(self):
    """ Returns a string for the specific child policy describing the progress. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def _get_policy_report_results_str(self):
    """ Returns a string for the specific child policy describing the progress. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  # Methods needed for initialisation ----------------------------------------
  def perform_initial_queries(self):
    """ Perform initial queries. """
    # If we already have some pre_eval points then do this.
    if (hasattr(self.options, 'prev_evaluations') and
        self.options.prev_evaluations is not None):
      # Add each point and val to the history
      for qinfo in self.options.prev_evaluations.qinfos:
        self.prev_eval_points.append(qinfo.point)
        self.prev_eval_vals.append(qinfo.val)
      self._problem_handle_prev_evals()
    else:
      # Get the initial points
      num_init_evals = int(self.options.num_init_evals)
      if num_init_evals > 0:
        num_init_evals = max(self.num_workers, num_init_evals)
        if hasattr(self.options, 'get_initial_qinfos') and \
           self.options.get_initial_qinfos is not None:
          init_qinfos = self.options.get_initial_qinfos(num_init_evals)
        else:
          init_qinfos = self._get_initial_qinfos(num_init_evals)
        for qinfo in init_qinfos:
          self.step_idx += 1
          self._wait_for_a_free_worker()
          self._dispatch_single_experiment_to_worker_manager(qinfo)

  def _problem_handle_prev_evals(self):
    """ Handles pre-evaluations. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def _get_initial_qinfos(self, num_init_evals):
    """ Returns the initial qinfos. Can be overridden by a child class. """
    # pylint: disable=unused-argument
    # pylint: disable=no-self-use
    return []

  def initialise_capital(self):
    """ Initialises capital. """
    if self.options.capital_type == 'return_value':
      self.spent_capital = 0.0
    elif self.options.capital_type == 'cputime':
      self.init_cpu_time_stamp = time.clock()
    elif self.options.capital_type == 'realtime':
      self.init_real_time_stamp = time.time()

  def get_curr_spent_capital(self):
    """ Computes the current spent time. """
    if self.options.capital_type == 'return_value':
      return self.spent_capital
    elif self.options.capital_type == 'cputime':
      return time.clock() - self.init_cpu_time_stamp
    elif self.options.capital_type == 'realtime':
      return time.time() - self.init_real_time_stamp

  def set_curr_spent_capital(self, spent_capital):
    """ Sets the current spent capital. Useful only in synthetic set ups."""
    if self.options.capital_type == 'return_value':
      self.spent_capital = spent_capital

  def run_experiment_initialise(self):
    """ Initialisation before running initialisation. """
    self.initialise_capital()
    self.perform_initial_queries()
    self._problem_run_experiments_initialise()
    self._policy_run_experiments_initialise()

  def _problem_run_experiments_initialise(self):
    """ Handles any initialisation for the problem before running experiments. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  def _policy_run_experiments_initialise(self):
    """ Handles any initialisation for the policy before running experiments. """
    raise NotImplementedError('Implement in a child class of BlackboxExperimenter.')

  # Methods needed for querying ----------------------------------------------------
  def _wait_till_free(self, is_free, poll_time):
    """ Waits until is_free returns true. """
    keep_looping = True
    while keep_looping:
      last_receive_time = is_free()
      if last_receive_time is not None:
        # Get the latest set of results and dispatch the next job.
        self.set_curr_spent_capital(last_receive_time)
        latest_results = self.worker_manager.fetch_latest_results()
        for qinfo in latest_results:
          if self.experiment_caller.is_mf() and not hasattr(qinfo, 'cost_at_fidel'):
            qinfo.cost_at_fidel = qinfo.eval_time
          self._update_history(qinfo)
          self._remove_from_in_progress(qinfo)
        self._add_data_to_model(latest_results)
        keep_looping = False
      else:
        time.sleep(poll_time)

  def _wait_for_a_free_worker(self):
    """ Checks if a worker is free and updates with the latest results. """
    self._wait_till_free(self.worker_manager.a_worker_is_free,
                         self.worker_manager.get_poll_time_real())

  def _wait_for_all_free_workers(self):
    """ Checks to see if all workers are free and updates with latest results. """
    self._wait_till_free(self.worker_manager.all_workers_are_free,
                         self.worker_manager.get_poll_time_real())

  def _add_to_in_progress(self, qinfos):
    """ Adds jobs to in progress. """
    for qinfo in qinfos:
      self.eval_idxs_in_progress.append(qinfo.step_idx)
      self.eval_points_in_progress.append(qinfo.point)

  def _remove_from_in_progress(self, qinfo):
    """ Removes a job from the in progress status. """
    completed_eval_idx = self.eval_idxs_in_progress.index(qinfo.step_idx)
    self.eval_idxs_in_progress.pop(completed_eval_idx)
    self.eval_points_in_progress.pop(completed_eval_idx)

  def _dispatch_single_experiment_to_worker_manager(self, qinfo):
    """ Dispatches an experiment to the worker manager. """
    # Create a new qinfo namespace and dispatch new job.
    qinfo.send_time = self.get_curr_spent_capital()
    qinfo.step_idx = self.step_idx
    self.worker_manager.dispatch_single_experiment(self.experiment_caller, qinfo)
    self._add_to_in_progress([qinfo])

  def _dispatch_batch_of_experiments_to_worker_manager(self, qinfos):
    """ Dispatches a batch of experiments to the worker manager. """
    for idx, qinfo in enumerate(qinfos):
      qinfo.send_time = self.get_curr_spent_capital()
      qinfo.step_idx = self.step_idx + idx
    self.worker_manager.dispatch_batch_of_experiments(self.func_caller, qinfos)
    self._add_to_in_progress(qinfos)

  # Some utilities ---------------------------------------------------------------
  def get_past_data(self):
    """ Returns the data in past evaluations. """
    X = self.prev_eval_points + self.history.query_points
    Y = self.prev_eval_vals + self.history.query_vals
    return X, Y

  # Methods needed for running experiments ---------------------------------------
  def _terminate_now(self):
    """ Returns true if we should terminate now. """
    if self.step_idx >= self.options.max_num_steps:
      self.reporter.writeln('Exceeded %d evaluations. Terminating Now!'%(
                            self.options.max_num_steps))
      return True
    return self.get_curr_spent_capital() >= self.available_capital

  def add_capital(self, capital):
    """ Adds capital. """
    self.available_capital += float(capital)

  def _determine_next_query(self):
    """ Determine the next point for evaluation. """
    raise NotImplementedError('Implement in a child class.!')

  def _determine_next_batch_of_queries(self, batch_size):
    """ Determine the next batch of eavluation points. """
    raise NotImplementedError('Implement in a child class.!')

  def _post_process_next_eval_point(self, point):
    """ Post-process the next point for evaluation. By default, returns same point. """
    #pylint: disable=no-self-use
    return point

  def _add_data_to_model(self, qinfos):
    """ Adds data to model. """
    pass

  def _build_new_model(self):
    """ Builds a new model. """
    self.last_model_build_at = self.step_idx
    self._child_build_new_model()

  def _child_build_new_model(self):
    """ Builds a new model. Pass by default but can be overridden in a child class. """
    pass

  def _update_capital(self, qinfos):
    """ Updates the capital according to the cost of the current query. """
    if not hasattr(qinfos, '__iter__'):
      qinfos = [qinfos]
    query_receive_times = []
    for idx in len(qinfos):
      if self.options.capital_type == 'return_value':
        query_receive_times[idx] = qinfos[idx].send_time + qinfos[idx].eval_time
      elif self.options.capital_type == 'cputime':
        query_receive_times[idx] = time.clock() - self.init_cpu_time_stamp
      elif self.options.capital_type == 'realtime':
        query_receive_times[idx] = time.time() - self.init_real_time_stamp
      # Finally add the receive time of the job to qinfo.
      qinfos[idx].receive_time = query_receive_times[idx]
      qinfos[idx].eval_time = qinfos[idx].receive_time - qinfos[idx].send_time
      if qinfos[idx].eval_time < 0:
        raise ValueError(('Something wrong with the timing. send: %0.4f, receive: %0.4f,'
               + ' eval: %0.4f.')%(qinfos[idx].send_time, qinfos[idx].receive_time,
               qinfos[idx].eval_time))
    # Compute the maximum of all receive times
    max_query_receive_times = max(query_receive_times)
    return max_query_receive_times

  # Methods for running experiments ----------------------------------------------
  def _asynchronous_run_experiment_routine(self):
    """ Optimisation routine for asynchronous part. """
    self._wait_for_a_free_worker()
    qinfo = self._determine_next_query()
    if self.experiment_caller.is_mf() and not hasattr(qinfo, 'fidel'):
      qinfo.fidel = self.experiment_caller.fidel_to_opt
    self._dispatch_single_experiment_to_worker_manager(qinfo)
    self.step_idx += 1

  def _synchronous_run_experiment_routine(self):
    """ Optimisation routine for the synchronous part. """
    self._wait_for_all_free_workers()
    qinfos = self._determine_next_batch_of_queries(self.num_workers)
    self._dispatch_batch_of_experiments_to_worker_manager(qinfos)
    self.step_idx += self.num_workers

  def _run_experiment_wrap_up(self):
    """ Wrap up before concluding running experiments. """
    self.worker_manager.close_all_queries()
    self._wait_for_all_free_workers()
    self._report_curr_results()
    # Store additional data
    self.history.num_jobs_per_worker = np.array(self._get_jobs_for_each_worker())

  def _main_loop_pre(self):
    """ Anything to be done before each iteration of the main loop. Mostly in case
        this is needed by a child class. """
    pass

  def _main_loop_post(self):
    """ Anything to be done after each iteration of the main loop. Mostly in case
        this is needed by a child class. """
    pass

  # run_experiments method --------------
  def run_experiments(self, max_capital):
    """ This is the main loop which executes the experiments in a loop. """
    self.add_capital(max_capital)
    self.run_experiment_initialise()

    # Main loop --------------------
    while not self._terminate_now():
      # Main loop pre
      self._main_loop_pre()
      # Experimentation step
      if self.is_asynchronous():
        self._asynchronous_run_experiment_routine()
      else:
        self._synchronous_run_experiment_routine()
      # Book keeeping
      if self.step_idx - self.last_model_build_at >= self.options.build_new_model_every:
        self._build_new_model()
      if self.step_idx - self.last_report_at >= self.options.report_results_every:
        self._report_curr_results()
      # Main loop post
      self._main_loop_post()

    # Wrap up and return
    self._run_experiment_wrap_up()
    return self._get_final_return_quantities()

  def _get_final_return_quantities(self):
    """ Gets the final quantities to be returned. Can be overriden by a child. """
    return self.history

