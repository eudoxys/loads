"""Cache manager"""

import os
import warnings

def cache_clear():
    """Clear cache files"""
    cachedir = os.path.join(os.path.dirname(__file__),".cache")

    for file in os.listdir(cachedir):

        filepath = os.path.join(cachedir,file)

        if os.path.isfile(filepath):

            try:

                os.unlink(filepath)

            # pylint: disable=broad-exception-caught
            except Exception as err:

                warnings.warn(f"cache {file=} delete failed: {err}")

if __name__ == "__main__":

    cache_clear()