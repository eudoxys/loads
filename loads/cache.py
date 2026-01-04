"""Cache manager

The cache manager handles the data cache for all downloaded data. The cache is
necessary to enhance the overall performance of the `loads` package. The cache
can be cleared using the `cli` command

    loads cache clear

# Example

    from loads.cache import Cache
    import pandas as pd
    cache = Cache(["ST","County","file.csv])
    if cache.exists():
        data = pd.read_csv(cache.pathname)
    else:
        data = pd.DataFrame({"test":[1,2,3]})
        data.to_csv(cache.pathname)
"""

import os
import stat
import warnings
import shutil

class Cache:

    CACHEDIR = os.path.join(os.path.dirname(__file__),".cache")

    def __init__(self,path:str|list[str]):
        """Construct a cache file handler"""
        if isinstance(path,str):
            path = [path]
        assert isinstance(path,list), f"{path=} must be a list"
        for name in path:
            assert isinstance(name,str), f"{name=} must be a string"
        self.path = path
        self.name = path[-1].replace(" ","_")
        self.pathname = os.path.join(self.CACHEDIR,*path).replace(" ","_")
        self.dirname = os.path.dirname(self.pathname)
        os.makedirs(self.dirname,exist_ok=True)

    def open(self,mode="r",encoding="utf-8"):
        """Open cache file

        # Arguments

        - `mode`: file open mode (see `open`)

        - `encoding`: file encoding (see `open`)

        # Returns

        - `io.IOBase`: file handle
        """
        assert isinstance(mode,str), f"{mode=} must be a string"
        assert isinstance(encoding,str), f"{encoding=} must be a string"
        return open(self.pathname,mode,encoding=encoding)

    def exists(self):
        """Tests for existence of cache file

        # Returns

        - `bool`: `True` if file exists, otherwise `False
        """
        return os.path.exists(self.pathname)

    def delete(self,ignore_errors:bool=True):
        """Delete the cache file

        # Arguments

        - `ignore_errors`: enables ignoring of `FileNotFoundError` exceptions

        # Exceptions

        - `FileNotFoundError`: the cache file was not found
        """
        assert isinstance(ignore_errors,bool), f"{ignore_errors=} must be a Boolean value"
        try:
            os.remove(self.pathname)
        except FileNotFoundError:
            if not ignore_errors:
                raise

    def __str__(self):
        return self.pathname

    def __repr__(self):
        return f"Cache(path={self.path})"

    @classmethod
    def clear(cls,
        path:list[str]=None,
        clear_ro:bool=True,
        ):
        """Clears the cache at the specified level

        # Arguments

        - `path`: specifies the path to clear, e.g., `["CA","Alameda"]`

        - `clear_ro`: enable clearing of read-only files
        """
        if path is None:
            path = []
        assert isinstance(path,list), f"{path=} must be a list"
        for name in path:
            assert isinstance(name,str), f"{name=} must be a string"
        assert isinstance(clear_ro,bool), f"{clear_ro=} must be a Boolean"
        def rm_ro(remove_call,path,_):
            os.chmod(path,stat.S_IWRITE)
            remove_call(path)
        shutil.rmtree(
            path=os.path.join(cls.CACHEDIR,*path),
            ignore_errors=True,
            onexc=rm_ro if clear_ro else None,
            )

def cache_clear(path=None):
    """Clear cache files

    # Argument

    - `path`: the path to clear, e.g., `["CA","Alameda"]`
    """
    Cache.clear(path)

if __name__ == "__main__":

    cache = Cache(["TEST","Test county","test name.csv"])
    print(cache.pathname)
    print(cache.dirname)
    print(cache.name)
    print(f"{cache=}")
    print(f"{cache}")
    Cache.clear(["TEST"])
