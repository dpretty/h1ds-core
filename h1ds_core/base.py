"""Base classes for interaction with database.

TODO: to  keep code  clean, let's  only have classess  which need  to be
subclassed to  access databases. At  present, this is only  BaseNode and
BaseURLProcessor

"""
import re
import inspect
import numpy as np

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.importlib import import_module

from h1ds_core.filters import BaseFilter, excluded_filters

data_module = import_module(settings.H1DS_DATA_MODULE)

# Match strings "f(fid)_name", where fid is the filter ID
filter_name_regex = re.compile('^f(?P<fid>\d+?)')

# Match strings "f(fid)_kwarg_(arg name)", where fid is the filter ID
filter_kwarg_regex = re.compile('^f(?P<fid>\d+?)_(?P<kwarg>.+)')

sql_type_mapping = {
    np.float32:"FLOAT",
    np.float64:"FLOAT",
    np.int32:"INT",
    np.int64:"INT",
    }

def remove_prefix(url):
    """Strip any prefix in the URL path."""
    if url.startswith("/"):
        url = url[1:]
    if hasattr(settings, "H1DS_DATA_PREFIX"):
        pref = settings.H1DS_DATA_PREFIX + "/"
        if url.startswith(pref):
            url = url[len(pref):]        
    return url

def apply_prefix(url):
    """Apply any prefix to the URL path."""
    if not url.startswith("/"):
        url = "/"+url
    if hasattr(settings, "H1DS_DATA_PREFIX"):
        if not url.startswith("/"+settings.H1DS_DATA_PREFIX+"/"):
            url = "/"+settings.H1DS_DATA_PREFIX+ url
    return url

def get_all_filters():
    """Get all filters from modules listed in settings.DATA_FILTER_MODULES."""
    filters = {}
    for filter_module_name in settings.DATA_FILTER_MODULES:
        mod = import_module(filter_module_name)
        mod_filters = [cl for name, cl in inspect.getmembers(mod) if
                       inspect.isclass(cl) and issubclass(cl, BaseFilter) and
                       not cl in excluded_filters]
        filters.update((f.get_slug(), f) for f in mod_filters)
    return filters
        
class FilterManager(object):
    """Get available filters for given data.

    FilterManager caches lookups to avoid repeated checks of filters for
    available datatypes.
    """
    def __init__(self):
        self.filters = get_all_filters()
        self.cache = {}

    def get_filters(self, data):
        """Get available processing filters for data object provided."""
        ndim = data.ndim if hasattr(data, "ndim") else 0
        if ndim == 0:
            _dt = type(data)
        else:
            _dt = data.dtype
        data_type = (ndim, _dt)
        if not self.cache.has_key(data_type):
            data_filters = {}
            for fname, filter_ in self.filters.iteritems():
                if filter_.is_filterable(data):
                    data_filters[fname] = filter_
            self.cache[data_type] = data_filters
        return self.cache[data_type]

filter_manager = FilterManager()


def get_latest_shot_function():
    """Get the module specified in settings.LATEST_SHOT_FUNCTION."""
    i = settings.LATEST_SHOT_FUNCTION.rfind('.')
    module = settings.LATEST_SHOT_FUNCTION[:i]
    attr = settings.LATEST_SHOT_FUNCTION[i+1:]
    try:
        mod = import_module(module)
    except ImportError as error:
        msg = 'Error importing module {}: "{}"'.format(module, error)
        raise ImproperlyConfigured(msg)
    try:
        func  = getattr(mod, attr)
    except AttributeError:
        msg = 'Module "{}" has no attribute "{}"'.format(module, attr)
        raise ImproperlyConfigured(msg)
    return func

class BaseURLProcessor(object):
    """Base class for mapping between URLs and data paths."""
    def __init__(self, **kwargs):
        """takes url or components.

        maps to /tree/shot/path.
        Use a subclass of this to change mapping.

        """
        url = kwargs.get('url', None)
        tree = kwargs.get('tree', None)
        shot = kwargs.get('shot', None)
        path = kwargs.get('path', None)
        if url != None:
            url = remove_prefix(url)
            self.tree, self.shot, self.path = self.get_components_from_url(url)
            if tree != None and tree != self.tree:
                raise AttributeError
            if shot != None and shot != self.shot:
                raise AttributeError
            if path != None and path != self.path:
                raise AttributeError
        else:
            self.tree, self.shot, self.path = tree, shot, path
    
    def get_components_from_url(self, url):
        stripped_url = url.strip("/")
        n_slash = stripped_url.count("/")
        if n_slash == 0:
            tree = self.deurlize_tree(stripped_url)
            shot = data_module.get_latest_shot(tree)
            path = self.deurlize_path("")
        elif n_slash == 1:
            t, s = stripped_url.split("/")            
            tree = self.deurlize_tree(t)
            shot = self.deurlize_shot(s)
            path = self.deurlize_path("")
        else:
            t, s, p = stripped_url.split("/", 2)            
            tree = self.deurlize_tree(t)
            shot = self.deurlize_shot(s)
            path = self.deurlize_path(p)
        return tree, shot, path
        
    def get_url(self):
        return apply_prefix("/".join([self.urlized_tree(),
                                      self.urlized_shot(),
                                      self.urlized_path()]))
        
    def get_url_for_tree(self, tree):
        """TODO: apply urlized_tree to tree arg"""
        return apply_prefix("/".join([tree, self.urlized_shot()]))
    
    def urlized_tree(self):
        return str(self.tree)

    def urlized_shot(self):
        return str(self.shot)

    def urlized_path(self):
        return str(self.path)

    def deurlize_tree(self, url_tree):
        if url_tree == "":
            return settings.DEFAULT_TREE
        else:
            return url_tree

    def deurlize_shot(self, url_shot):
        return int(url_shot)

    def deurlize_path(self, url_path):
        return url_path

class BaseNode(object):
    def __init__(self, url_processor=None):
        self.url_processor = url_processor
        self.filter_history = []
        self.data = None
        self.dim = None
        self.labels = []
        self.units = []
        
    def apply_filters(self, request):
        for fid, name, kwargs in get_filter_list(request):
            self.apply_filter(fid, name, **kwargs)
        
    def apply_filter(self, fid, name, **kwargs):
        # make sure data and dim can be accessed via node.data, node.dim... 
        d = self.get_data()
        dim = self.get_dim()
        labels = self.get_labels()
        f_kwargs = self.preprocess_filter_kwargs(kwargs)
        #filter_class = filter_manager.filters[name](*f_args, **f_kwargs)
        filter_class = filter_manager.filters[name](**f_kwargs)
        filter_class.apply(self)
        
        #self.filter_history.append((fid, name, kwargs))
        self.filter_history.append((fid, filter_class, kwargs))
        #self.summary_dtype = sql_type_mapping.get(type(self.data))
        #self.available_filters = get_dtype_mappings(self.data)['filters']
        #self.available_views = get_dtype_mappings(self.data)['views'].keys()

    def preprocess_filter_kwargs(self, kwargs):
        # TODO: should filters.http_arg be put here instead?
        for key, val in kwargs.iteritems():
            if isinstance(val, str) and "__shot__" in val:
                shot_str = str(self.url_processor.shot)
                kwargs[key] = val.replace("__shot__", shot_str)
        return kwargs
        
    def get_data(self):
        if type(self.data) == type(None):
            self.data = self.get_raw_data()
        return self.data

    def get_raw_dim(self):
        return None
    
    def get_dim(self):
        # TODO - scalars etc will have dim None (or should they have
        # dim 0), shouldn't re-read from node for these cases...
        if type(self.dim) == type(None):
            self.dim = self.get_raw_dim()
        return self.dim
                    
    def get_raw_data(self):
        return None
    
    def get_parent(self):
        return None

    def get_children(self):
        return None

    def get_ancestors(self):
        ancestors = []
        p = self.get_parent()
        if p != None:
            ancestors.extend(p.get_ancestors())
            ancestors.append(p)
        return ancestors
        
    def get_long_name(self):
        return unicode(self.url_processor.path)

    def get_short_name(self):
        return unicode(self.url_processor.path)

    def __str__(self):
        return self.get_long_name()

    def __repr__(self):
        return self.get_long_name()

    def get_summary_dtype(self):
        d = self.get_data()
        return sql_type_mapping.get(type(d), None)

    def get_available_filters(self):
        return filter_manager.get_filters(self.data)

    def get_ndim(self):
        """get ndim from data"""
        data = self.get_data()
        return data.ndim if hasattr(data, 'ndim') else 0

    def get_metadata(self):
        return dict()

    def _get_shape_from_data(self):
        data = self.get_data()
        try:
            return data.shape
        except AttributeError:
            return 0

    def _get_shape_from_dim(self):
        dim = self.get_dim()
        try:
            dim_lengths = tuple(len(i) for i in dim)
        except TypeError:
            return 0
        return dim_lengths
    
    def consistent_dim(self):
        # check that data and dim shapes match
        
        data_shape = self._get_shape_from_data()
        dim_shape = self._get_shape_from_dim()
        return data_shape == dim_shape

    def parameterised_dim(self):
        """Return start, delta, length for dimension data."""        
        pdim = {}
        dim = self.get_dim()
        dim_shape = self._get_shape_from_dim()
        if dim_shape == 0:
            pdim['ndim'] = 0
            return pdim
        else:
            pdim['ndim'] = len(dim_shape)
            
        for di, d in enumerate(dim_shape):
            pdim[di] = {'length':d}
            if pdim[di]['length'] > 0:
                darr = np.array(dim[di])
                pdim[di]['first'] = darr[0]
                pdim[di]['delta'] = np.mean(np.diff(darr))
                delta_arr = pdim[di]['delta']*np.arange(pdim[di]['length'])
                reconst_dim = delta_arr + pdim[di]['first']
                pdim[di]['rms_err'] = np.sqrt(np.mean((darr - reconst_dim)**2))
        return pdim

    def discretised_data(self, error_threshold=1.e-3, assert_dtype=None):
        """
        return int array of data with scales (min, delta)

        TODO: return smallest dtype which falls within error threshold
        using Boyd's discretise_array

        if assert_dtype (integer dtype) is provided, error_threshold is ignored.

        """
        
        data = self.get_data()
        data_min, data_max = np.min(data), np.max(data)
        dtype_info = np.iinfo(assert_dtype)
        dtype_min, dtype_max = dtype_info.min, dtype_info.max
        normalised_data = (data-data_min)/(data_max-data_min)
        rescaled_data = normalised_data*(dtype_max-dtype_min) + dtype_min
        recast_data = assert_dtype(rescaled_data)

        ret_val = {'data':recast_data,
                   'min':data_min,
                   'delta':(data_max-data_min)/(dtype_max-dtype_min)}

        reconstructed_data = ret_val['delta']*recast_data+data_min
        ret_val['rms_err'] = np.sqrt(np.mean((data-reconstructed_data)**2))

        return ret_val

    def get_labels(self):
        # [data label, dim0 label, dim1 label, etc]
        if not self.labels:
            ndim = self.get_ndim()
            self.labels = ["data"]
            self.labels.extend(["d%d" %i for i in xrange(ndim)])
        return self.labels

    def get_units(self):
        # [data units, dim0 units, dim1 units, etc]
        if not self.units:
            ndim = self.get_ndim()
            self.units = ["data units"]
            self.units.extend(["d%d units" %i for i in xrange(ndim)])
        return self.units

    def get_info(self):
        # node info to return to user via html, xml etc.
        node_info = {
            'data': self.get_data(),
            'dim': self.get_dim(),
            'name_long': self.get_long_name(),
            'name_short': self.get_short_name(),
            'ndim': self.get_ndim(),
            'metadata': self.get_metadata(),
            'labels': self.get_labels(),
            'units': self.get_units(),
            }
        return node_info


        
def get_filter_list(request):
    """Parse GET query sring and return sorted list of filter names.

    Arguments:
    request -- a HttpRequest instance with HTTP GET parameters.
    
    """
    filter_list = []

    if not request.method == 'GET':
        # If the HTTP method is not GET, return an empty list.
        return filter_list

    # First, create a dictionary with filter numbers as keys:
    # e.g. {1:{'name':filter, 'args':{1:arg1, 2:arg2, ...}, kwargs:{}}
    # note  that the  args  are stored  in  a dictionary  at this  point
    # because we cannot assume GET query will be ordered.
    filter_dict = {}
    for key, value in request.GET.iteritems():
        kwarg_match = filter_kwarg_regex.match(key)
        if kwarg_match != None:
            fid = int(kwarg_match.groups()[0])
            kwarg = kwarg_match.groups()[1]
            if not filter_dict.has_key(fid):
                filter_dict[fid] = {'name':"", 'kwargs':{}}
            filter_dict[fid]['kwargs'][kwarg] = value
            continue
        
        name_match = filter_name_regex.match(key)
        if name_match != None:
            fid = int(name_match.groups()[0])
            if not filter_dict.has_key(fid):
                filter_dict[fid] = {'name':"", 'kwargs':{}}
            filter_dict[fid]['name'] = value
            continue
    
    for fid, filter_data in sorted(filter_dict.items()):
        filter_list.append([fid, filter_data['name'], filter_data['kwargs']])
                           
    return filter_list
