import six
from hashlib import sha1
from collections import OrderedDict, Iterable
from six.moves.urllib.parse import urlparse
import io
from dataset.numpy_util import npy_load, npy_save, is_numpy_array, has_numpy

QUERY_STEP = 1000
row_type = OrderedDict


class DatasetException(Exception):
    pass


def convert_row(row_type, row):
    if row is None:
        return None
    if has_numpy:
        return convert_blobs(row_type(row.items()))
    return row_type(row.items())


def iter_result_proxy(rp, step=None):
    """Iterate over the ResultProxy."""
    while True:
        if step is None:
            chunk = rp.fetchall()
        else:
            chunk = rp.fetchmany(step)
        if not chunk:
            break
        for row in chunk:
            yield row


class ResultIter(object):
    """ SQLAlchemy ResultProxies are not iterable to get a
    list of dictionaries. This is to wrap them. """

    def __init__(self, result_proxy, row_type=row_type, step=None):
        self.row_type = row_type
        self.result_proxy = result_proxy
        self.keys = list(result_proxy.keys())
        self._iter = iter_result_proxy(result_proxy, step=step)

    def __next__(self):
        return convert_row(self.row_type, next(self._iter))

    next = __next__

    def __iter__(self):
        return self

    def close(self):
        self.result_proxy.close()


def normalize_column_name(name):
    """Check if a string is a reasonable thing to use as a column name."""
    if not isinstance(name, six.string_types):
        raise ValueError('%r is not a valid column name.' % name)

    # limit to 63 characters
    name = name.strip()[:63]
    # column names can be 63 *bytes* max in postgresql
    if isinstance(name, six.text_type):
        while len(name.encode('utf-8')) >= 64:
            name = name[:len(name) - 1]

    if not len(name) or '.' in name or '-' in name:
        raise ValueError('%r is not a valid column name.' % name)
    return name


def normalize_table_name(name):
    """Check if the table name is obviously invalid."""
    if not isinstance(name, six.string_types):
        raise ValueError("Invalid table name: %r" % name)
    name = name.strip()[:63]
    if not len(name):
        raise ValueError("Invalid table name: %r" % name)
    return name


def safe_url(url):
    """Remove password from printed connection URLs."""
    parsed = urlparse(url)
    if parsed.password is not None:
        pwd = ':%s@' % parsed.password
        url = url.replace(pwd, ':*****@')
    return url


def index_name(table, columns):
    """Generate an artificial index name."""
    sig = '||'.join(columns)
    key = sha1(sig.encode('utf-8')).hexdigest()[:16]
    return 'ix_%s_%s' % (table, key)


def ensure_tuple(obj):
    """Try and make the given argument into a tuple."""
    if obj is None:
        return tuple()
    if isinstance(obj, Iterable) and not isinstance(obj, six.string_types):
        return tuple(obj)
    return obj,


def ndarray2binary(array):
    """Convert a numpy ndarray to a binary string suited for LargeBinary storage"""
    if not is_numpy_array(array):
        raise TypeError("The argument has to be a numpy ndarray")
    out = io.BytesIO()
    npy_save(out, array)
    out.seek(0)
    return out.read()


def binary2ndarray(string):
    """Convert a binary string to ndarray"""
    data = io.BytesIO(string)
    data.seek(0)
    return npy_load(data)


def convert_blobs(row):
    """Tries to convert the blob entries into the correct datatypes"""
    for key in row.keys():
        if isinstance(row[key], str):
            # Numpy's binary format starts with the "magic" string \x93NUMPY
            if row[key].startswith("\x93NUMPY"):
                array = binary2ndarray(row[key])
                row[key] = array
        elif isinstance(row[key], bytes):
            if row[key][:6] == b"\x93NUMPY":
                array = binary2ndarray(row[key])
                row[key] = array
    return row


def pad_chunk_columns(chunk):
    """Given a set of items to be inserted, make sure they all have the
    same columns by padding columns with None if they are missing."""
    columns = set()
    for record in chunk:
        columns.update(record.keys())
    for record in chunk:
        for column in columns:
            record.setdefault(column, None)
    return chunk
