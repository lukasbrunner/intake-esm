import hashlib
import os
from urllib.request import urlopen, urlretrieve

import pandas as pd
from intake.utils import yaml_load

from . import config

_default_cache_dir = config.get('database-directory')
_default_cache_dir = f'{_default_cache_dir}/bld-collection-input'

aliases = [
    'CESM1-LE',
    'GLADE-CMIP5',
    'GLADE-CMIP6',
    'GLADE-RDA-ERA5',
    'GLADE-GMET',
    'MPI-GE',
    'AWS-CESM1-LE',
    'GLADE-NA-CORDEX',
    'mistral-CMIP5',
    'mistral-CMIP6',
    'mistral-MPIGE',
]

true_file_names = [
    'cesm1-le-collection',
    'glade-cmip5-collection',
    'glade-cmip6-collection',
    'glade-rda-era5-collection',
    'glade-gmet-collection',
    'mpige-collection',
    'aws-cesm1-le-collection',
    'glade-na-cordex-collection',
    'mistral-cmip5-collection',
    'mistral-cmip6-collection',
    'mistral-mpige-collection',
]


descriptions = [
    'Community Earth System Model Large Ensemble (CESM LENS) data holdings @ NCAR',
    'Coupled Model Intercomparison Project - Phase 5 data holdings on the CMIP Analysis Platform @ NCAR',
    'Coupled Model Intercomparison Project - Phase 6 data holdings on the CMIP Analysis Platform @ NCAR',
    'ECWMF ERA5 Reanalysis data holdings @ NCAR',
    'The Gridded Meteorological Ensemble Tool data holdings',
    'The Max Planck Institute for Meteorology (MPI-M) Grand Ensemble (MPI-GE) data holdings',
    'Community Earth System Model Large Ensemble (CESM LENS) data holdings publicly available on Amazon S3 (us-west-2 region)',
    'The North American CORDEX program data holdings @ NCAR',
    'Coupled Model Intercomparison Project - Phase 5 data holdings @ \
     dkrz.mistral',
    'Coupled Model Intercomparison Project - Phase 6 data holdings @ \
     dkrz.mistral',
    'Max Planck Institute for Meteorology Grand Ensemble (MPI-ESM GE) CMORized \
     data holdings @ dkrz.mistral',
]


FILE_ALIAS_DICT = dict(zip(aliases, true_file_names))
FILE_DESCRIPTIONS = dict(zip(aliases, descriptions))


def _file_md5_checksum(fname):
    hash_md5 = hashlib.md5()
    with open(fname, 'rb') as f:
        hash_md5.update(f.read())
    return hash_md5.hexdigest()


def _get_collection_input_files():
    """Prints out available collection definitions for the user to load if no args are
       given.
    """

    print(
        '*********************************************************************\n'
        '* The following collection inputs are supported out-of-the-box *\n'
        '*********************************************************************\n'
    )
    for key in FILE_DESCRIPTIONS.keys():
        print(f"'{key}': {FILE_DESCRIPTIONS[key]}")


def load_collection_input_file(
    name=None,
    cache=True,
    cache_dir=_default_cache_dir,
    github_url='https://github.com/NCAR/intake-esm-datastore',
    branch='master',
    extension='collection-input',
):
    """Load collection definition from an online repository.

    Parameters
    ----------

    name: str, default (None)
        Name of the yaml file containing collection definition, without the .yml extension.
        If None, this function prints out the available collection definitions to specify.

    cache: bool, optional
         If True, cache collection definition locally for use on later calls.

    cache_dir: str, optional
        The directory in which to search for and cache the downloaded file.

    github_url: str, optional
        Github repository where the collection definition is stored.

    branch: str, optional
         The git branch to download from.

    extension: str, optional Subfolder within the repository where the
        collection definition file is stored.

    Returns
    -------

    The desired collection definition dictionary
    """

    if name is None:
        return _get_collection_input_files()

    name, ext = os.path.splitext(name)
    if not ext.endswith('.yml'):
        ext += '.yml'

    if name in FILE_ALIAS_DICT.keys():
        name = FILE_ALIAS_DICT[name]

    longdir = os.path.expanduser(cache_dir)
    fullname = name + ext
    localfile = os.sep.join((longdir, fullname))
    md5name = name + '.md5'
    md5file = os.sep.join((longdir, md5name))

    if extension is not None:
        url = '/'.join((github_url, 'raw', branch, extension, fullname))
        url_md5 = '/'.join((github_url, 'raw', branch, extension, md5name))

    else:
        url = '/'.join((github_url, 'raw', branch, fullname))
        url_md5 = '/'.join((github_url, 'raw', branch, md5name))

    if not os.path.exists(localfile):
        os.makedirs(longdir, exist_ok=True)
        urlretrieve(url, localfile)
        urlretrieve(url_md5, md5file)

    with open(md5file, 'r') as f:
        localmd5 = f.read()

    with urlopen(url_md5) as f:
        remotemd5 = f.read().decode('utf-8')

    if localmd5 != remotemd5:
        os.remove(localfile)
        os.remove(md5file)
        msg = """
        Try downloading the file again. There was a confliction between
        your local .md5 file compared to the one in the remote repository,
        so the local copy has been removed to resolve the issue.
        """
        raise IOError(msg)

    with open(localfile) as f:
        d = yaml_load(f)

    if not cache:
        os.remove(localfile)

    return d


def _filter_query_results(query_results, path_column_name):
    """Filter for entries where file_basename is the same and remove all
       but the first ``direct_access = True`` row."""
    import os

    query_results['store_basename'] = query_results[path_column_name].map(
        lambda x: os.path.basename(x)
    )
    groups = query_results.groupby('store_basename')

    gps = []
    for _, group in groups:

        g = group[group['direct_access']]
        # File does not exist on resource with high priority
        if g.empty:
            gps.append(group)

        else:
            gps.append(g)

    query_results = pd.concat(gps)
    return query_results


def _ensure_file_access(query_results, path_column_name='path'):
    """Ensure that requested files are available locally.
    Paramters
    ---------
    query_results : `pandas.DataFrame`
        Results of a query.
    Returns
    -------
    local_urlpaths : list
        List of urls to access files in `query_results`.
    """

    from .storage import _get_hsi_stores, _posix_symlink

    resource_types = {'hsi': _get_hsi_stores, 'copy-to-cache': _posix_symlink}

    data_cache_directory = config.get('data-cache-directory')

    os.makedirs(data_cache_directory, exist_ok=True)

    file_remote_local = {k: [] for k in resource_types.keys()}

    query_results = _filter_query_results(query_results, path_column_name)

    local_urlpaths = []
    for idx, row in query_results.iterrows():
        if row.direct_access:
            local_urlpaths.append(row[path_column_name])

        else:
            file_remote = row[path_column_name]
            file_local = os.path.join(data_cache_directory, os.path.basename(file_remote))
            local_urlpaths.append(file_local)

            if not os.path.exists(file_local):
                if row.resource_type not in resource_types:
                    raise ValueError(f'unknown resource type: {row.resource_type}')

                file_remote_local[row.resource_type].append((file_remote, file_local))

    for res_type in resource_types:
        if file_remote_local[res_type]:
            print(f'transfering {len(file_remote_local[res_type])} files')
            resource_types[res_type](file_remote_local[res_type])

    query_results[path_column_name] = local_urlpaths

    return query_results
