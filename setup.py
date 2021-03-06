import os
import sys

from fnmatch import fnmatchcase

from distutils.util import convert_path
from setuptools import setup, find_packages


def read(*path):
    return open(os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                *path)).read()

# Provided as an attribute, so you can append to these instead
# of replicating them:
standard_exclude = ["*.py", "*.pyc", "*~", ".*", "*.bak"]
standard_exclude_directories = [
    ".*", "CVS", "_darcs", "./build",
    "./dist", "EGG-INFO", "*.egg-info"
]


# Copied from paste/util/finddata.py
def find_package_data(where=".", package="", exclude=standard_exclude,
        exclude_directories=standard_exclude_directories,
        only_in_packages=True, show_ignored=False):
    """
    Return a dictionary suitable for use in ``package_data``
    in a distutils ``setup.py`` file.

    The dictionary looks like::

        {"package": [files]}

    Where ``files`` is a list of all the files in that package that
    don't match anything in ``exclude``.

    If ``only_in_packages`` is true, then top-level directories that
    are not packages won't be included (but directories under packages
    will).

    Directories matching any pattern in ``exclude_directories`` will
    be ignored; by default directories with leading ``.``, ``CVS``,
    and ``_darcs`` will be ignored.

    If ``show_ignored`` is true, then all the files that aren't
    included in package data are shown on stderr (for debugging
    purposes).

    Note patterns use wildcards, or can be exact paths (including
    leading ``./``), and all searching is case-insensitive.
    """

    out = {}
    stack = [(convert_path(where), "", package, only_in_packages)]
    while stack:
        where, prefix, package, only_in_packages = stack.pop(0)
        for name in os.listdir(where):
            fn = os.path.join(where, name)
            if os.path.isdir(fn):
                bad_name = False
                for pattern in exclude_directories:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        if show_ignored:
                            print >> sys.stderr, (
                                "Directory %s ignored by pattern %s"
                                % (fn, pattern))
                        break
                if bad_name:
                    continue
                if (os.path.isfile(os.path.join(fn, "__init__.py"))
                    and not prefix):
                    if not package:
                        new_package = name
                    else:
                        new_package = package + "." + name
                    stack.append((fn, "", new_package, False))
                else:
                    stack.append((fn, prefix + name + "/", package,
                                    only_in_packages))
            elif package or not only_in_packages:
                # is a file
                bad_name = False
                for pattern in exclude:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        if show_ignored:
                            print >> sys.stderr, (
                                "File %s ignored by pattern %s"
                                % (fn, pattern))
                        break
                if bad_name:
                    continue
                out.setdefault(package, []).append(prefix + name)
    return out


excluded_directories = standard_exclude_directories + ["example", "tests"]
package_data = find_package_data(exclude_directories=excluded_directories)

DESCRIPTION = "A CMS for Nonprofits"

LONG_DESCRIPTION = None
try:
    LONG_DESCRIPTION = open('README.md').read()
except:
    pass

CLASSIFIERS = [
    'Framework :: Django',
]

setup(
    name='tendenci',
    version='5.1.0',
    packages=find_packages(),
    package_data=package_data,
    author='Schipul',
    author_email='programmers@schipul.com',
    url='http://github.com/tendenci/tendenci/',
    license='GPL3',
    description=DESCRIPTION,
    long_description=LONG_DESCRIPTION,
    platforms=['any'],
    classifiers=CLASSIFIERS,
    include_package_data=True,
    dependency_links=[
#         "http://github.com/tendenci/geraldo/tarball/master#egg=Geraldo-0.4.14",
        "http://a.pypi.python.org/",
        "http://g.pypi.python.org/",
    ],
    setup_requires=[
        "Reportlab==2.5",
    ],
    install_requires=[
        "Django==1.4.1",
        "Reportlab==2.5",
        "PIL==1.1.7",
        "South==0.7.3",
        "anyjson>=0.2.4",
        "django-authority>=0.4",
        "django-avatar>=1.0.4",
        "django-form-utils>=0.1.8",
        "django-pagination>=1.0.7",
        "django-photologue>=2.3",
        "django-picklefield>=0.1.6",
        "django-simple-captcha>=0.1.7",
        "django-tagging>=0.3.1",
        "django-tinymce==1.5.1.dev100",
        "django-haystack==1.2.7",
        "feedparser>=4.1",
        "httplib2>=0.4.0",
        "pytz>=2010h",
        "simplejson>=2.0.9",
        "webcolors>=1.3.1",
        "xlrd==0.7.3",
        "xlwt>=0.7.2",
        "pyparseuri>=0.1",
        "pysolr==2.0.15",
        "BeautifulSoup==3.2.1",
        "oauth2>=1.5.167",
        "python_openid>=2.2",
        "ordereddict==1.1",
        "createsend>=0.3.2",
        "celery==3.0.1",
        "django-celery==3.0.1",
        "django-kombu>=0.9.4",
        "mimeparse>=0.1.3",
        "python-dateutil>=1.5",
        "pdfminer==20110515",
        "slate==0.3",
        "stripe==1.7.2",
        "pycrypto==2.6",
        "boto==2.5.2",
        "django-timezones==0.2",
        "django-ses==0.4.1",
#         "Geraldo==0.4.14",
        "django-tastypie",
        "johnny-cache==1.4",
        "django-debug-toolbar"
    ],
)