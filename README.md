# Haal Centraal API

This is a proxy service to connect to the Haal Centraal API.

# Reason

Haal Centraal offers national services for accessing government data.
These services are designed to support broad access, and don't offer much refined authorization policies.
Such feature has to be implemented by each municipality that implements the API.
This service does this based on policy files defined in "Amsterdam Schema".

# Installation

Requirements:

* Python >= 3.12
* Recommended: Docker/Docker Compose (or pyenv for local installs)

## Using Docker Compose

Run docker compose:
```
    docker compose up
```

Navigate to `localhost:8095`.

## Using Local Python

Create a virtualenv:

```
    python3 -m venv venv
    source venv/bin/activate
```

Install all packages in it:
```
    pip install -U wheel pip
    cd src/
    make install  # installs src/requirements_dev.txt
```

Start the Django application:
```
    export PUB_JWKS="$(cat jwks_test.json)"
    export DJANGO_DEBUG=true

    ./manage.py runserver localhost:8000
```

## Environment Settings

The following environment variables are useful for configuring a local development environment.

To connect to an authentication provider, setup the following environment variables:
* `OAUTH_CLIENT_ID`: The client id of the application
* `OAUTH_JWKS_URL`: The JWKS URL of the authentication provider.
* `OAUTH_URL`:  The auth URL of the authentication provider.

# Developer Notes

## Package Management

The packages are managed with *pip-compile*.

To add a package, update the `requirements.in` file and run `make requirements`.
This will update the "lockfile" aka `requirements.txt` that's used for pip installs.

To upgrade all packages, run `make upgrade`, followed by `make install` and `make test`.
Or at once if you feel lucky: `make upgrade install test`.

## Environment Settings

Consider using *direnv* for automatic activation of environment variables.
It automatically sources an ``.envrc`` file when you enter the directory.
This file should contain all lines in the `export VAR=value` format.

In a similar way, *pyenv* helps to install the exact Python version,
and will automatically activate the virtualenv when a `.python-version` file is found:

```
    pyenv install 3.12.4
    pyenv virtualenv 3.12.4 haal-centraal-proxy
    echo haal-centraal-proxy > .python-version
```
