# dj-watchfiles

[![GitHub Actions (CI)](https://github.com/xshapira/dj-watchfiles/workflows/Run%20tests%20and%upload%20coverage/badge.svg)](https://github.com/xshapira/dj-watchfiles)
[![Codecov](https://img.shields.io/codecov/c/gh/xshapira/dj-watchfiles?color=%2334D058)](https://codecov.io/gh/xshapira/dj-watchfiles)
[![PyPI version](https://badge.fury.io/py/dj-watchfiles.svg)](https://badge.fury.io/py/dj-watchfiles)

Use [watchfiles](https://watchfiles.helpmanual.io/) in Django's autoreloader.

---

`dj-watchfiles` is a fork of [django-watchfiles](https://github.com/adamchainz/django-watchfiles), adds support for managing verbosity level.

---

## Requirements

Python 3.9 to 3.13 supported.

Django 4.2 to 5.1 supported.

## Installation

1. Install with **pip**:

   ```sh
   python -m pip install dj-watchfiles
   ```

2. Install with **uv**:

   ```sh
   uv add dj-watchfiles
   ```

3. Add dj-watchfiles to your INSTALLED_APPS:

   ```sh
   INSTALLED_APPS = [
        ...,
        "dj_watchfiles",
        ...,
    ]
   ```

That's it!

## Verbosity configuration

You can control the verbosity level either through Django settings or CLI.

1. **Django Settings**

   ```py

    WATCHFILES = {
      "verbosity": 2,  # Default is 1
    }

   ```

1. **CLI**

   ```sh
    python manage.py runserver --verbosity 2
   ```

### Verbosity Levels

| Verbosity level | Log level | What you'll see |
| --- | --- | --- |
| 0 | ERROR | Only errors |
| 1 | WARNING | Warnings and errors (Default) |
| 2 | INFO | Info, warnings, and errors |
| 3 | DEBUG | All messages including debug info |

Other settings you can get from the project settings `WATCHFILES`, e.g.:

```py
WATCHFILES = {
     "watch_filter": "path.to.custom_filter",
     "raise_interrupt": False,
     "debug": True,  # False by default
   }
```

**Note:** Setting `debug = True` is more like a hard override that ignores the verbosity setting completely and sets the verbosity level to 3 (DEBUG level).

---

Django doesn't provide an official API for alternative autoreloader classes.
Therefore, dj-watchfiles monkey-patches django.utils.autoreload to make its own reloader the only available class.
You can tell it is installed as runserver will list WatchfilesReloader as in use:

```sh
$ ./manage.py runserver
Watching for file changes with WatchfilesReloader
...

```

Unlike Django's built-in WatchmanReloader, there is no need for a fallback to StatReloader, since watchfiles implements its own internal fallback to using stat.
