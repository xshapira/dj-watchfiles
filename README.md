# dj-watchfiles

[![CI](https://img.shields.io/github/actions/workflow/status/xshapira/dj-watchfiles/main.yml.svg?branch=main&style=for-the-badge)](https://github.com/xshapira/dj-watchfiles/actions?workflow=CI)
[![Coverage](https://img.shields.io/badge/Coverage-100%25-success?style=for-the-badge)](https://github.com/xshapira/dj-watchfiles/actions?workflow=CI)
[![PyPI](https://img.shields.io/pypi/v/dj-watchfiles.svg?style=for-the-badge)](https://pypi.org/project/dj-watchfiles/)

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
        "dj-watchfiles",
        ...,
    ]
   ```

That's it!

## Verbosity configuration

...

Django doesn't provide an official API for alternative autoreloader classes.
Therefore, dj-watchfiles monkey-patches django.utils.autoreload to make its own reloader the only available class.
You can tell it is installed as runserver will list WatchfilesReloader as in use:

```sh
$ ./manage.py runserver
Watching for file changes with WatchfilesReloader
...

```

Unlike Django's built-in WatchmanReloader, there is no need for a fallback to StatReloader, since watchfiles implements its own internal fallback to using stat.
