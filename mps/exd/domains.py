"""
  Harness to manage optimisation domains.
  -- kandasamy@cs.cmu.edu
"""

# pylint: disable=invalid-name
# pylint: disable=arguments-differ

import numpy as np

class Domain(object):
  """ Domain class. An abstract class which implements domains. """

  def get_type(self):
    """ Returns the type of the domain. """
    raise NotImplementedError('Implement in a child class.')

  def get_dim(self):
    """ Returns the dimension of the space. """
    raise NotImplementedError('Implement in a child class.')

  def is_a_member(self, point):
    """ Returns True if point is a member of this domain. """
    raise NotImplementedError('Implement in a child class.')


# Universal Domain ----------
class UniversalDomain(Domain):
  """ A universal domian. Everything is a part of this.
      Used mostly in instances where the domain is not critical for lazy coding.
  """

  def get_type(self):
    """ Returns the type of the domain. """
    return 'universal'

  def get_dim(self):
    """ Return the dimensions. """
    return None

  def is_a_member(self, _):
    """ Returns true if point is in the domain. """
    return True

  def __str__(self):
    """ Returns a string representation. """
    return 'Universal Domain'


# Euclidean spaces ---------
class EuclideanDomain(Domain):
  """ Domain for Euclidean spaces. """

  def __init__(self, bounds):
    """ Constructor. """
    self.bounds = np.array(bounds)
    self.dim = len(bounds)
    super(EuclideanDomain, self).__init__()

  def get_type(self):
    """ Returns the type of the domain. """
    return 'euclidean'

  def get_dim(self):
    """ Return the dimensions. """
    return self.dim

  def is_a_member(self, point):
    """ Returns true if point is in the domain. """
    return is_within_bounds(self.bounds, point)

  def __str__(self):
    """ Returns a string representation. """
    return 'Euclidean Domain: %s'%(_get_bounds_as_str(self.bounds))


# Integral spaces ------------
class IntegralDomain(Domain):
  """ Domain for vector valued integers. """

  def __init__(self, bounds):
    """ Constructor. """
    self.bounds = np.array(bounds, dtype=np.int)
    self.dim = len(bounds)
    super(IntegralDomain, self).__init__()

  def get_type(self):
    """ Returns the type of the domain. """
    return 'integral'

  def get_dim(self):
    """ Return the dimensions. """
    return self.dim

  def is_a_member(self, point):
    """ Returns true if point is in the domain. """
    are_ints = [isinstance(x, (int, np.int)) for x in point]
    return all(are_ints) and is_within_bounds(self.bounds, point)

  def __str__(self):
    """ Returns a string representation. """
    return 'Integral Domain: %s'%(_get_bounds_as_str(self.bounds))


# Discrete spaces -------------
class DiscreteDomain(Domain):
  """ A Domain for discrete objects. """

  def __init__(self, list_of_items):
    """ Constructor. """
    self.list_of_items = list_of_items
    self.size = len(list_of_items)

  def get_type(self):
    """ Returns the type of the domain. """
    return 'discrete'

  def get_dim(self):
    """ Return the dimensions. """
    return 1

  def is_a_member(self, point):
    """ Returns true if point is in the domain. """
    return point in self.list_of_items

  def __str__(self):
    """ Returns a string representation. """
    base_str = 'Discrete Domain(%d)'%(self.size)
    if self.size < 4:
      return '%s: %s'%(base_str, self.list_of_items)
    return base_str


# A product of discrete spaces -----------
class ProdDiscreteDomain(Domain):
  """ A product of discrete objects. """

  def __init__(self, list_of_list_of_items):
    """ Constructor. """
    self.list_of_list_of_items = list_of_list_of_items
    self.dim = len(list_of_list_of_items)
    self.size = np.prod([len(loi) for loi in list_of_list_of_items])

  def get_type(self):
    """ Returns the type of the domain. """
    return 'prod_discrete'

  def get_dim(self):
    """ Return the dimensions. """
    return self.dim

  def is_a_member(self, point):
    """ Returns true if point is in the domain. """
    if not hasattr(point, '__iter__') or len(point) != self.dim:
      return False
    ret = [elem in loi for elem, loi in zip(point, self.list_of_list_of_items)]
    return all(ret)

  def __str__(self):
    """ Returns a string representation. """
    return 'Prod Discrete Domain(d=%d, size=%d)'%(self.dim, self.size)


# Utilities we will need for the above ------------------------------------------
def is_within_bounds(bounds, point):
  """ Returns true if point is within bounds. point is a d-array and bounds is a
      dx2 array. bounds is expected to be an np.array object.
  """
  point = np.array(point)
  if point.shape != (bounds.shape[0],):
    return False
  above_lb = np.all((point - bounds[:, 0] >= 0))
  below_ub = np.all((bounds[:, 1] - point >= 0))
  return above_lb * below_ub

def _get_bounds_as_str(bounds):
  """ returns a string representation of bounds. """
  bounds_list = [list(b) for b in bounds]
  return str(bounds_list)


# Ordinal Spaces ---------------------------------------------------------------------
