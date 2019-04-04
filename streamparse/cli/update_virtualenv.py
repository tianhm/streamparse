"""
Create or update a virtualenv on the Storm workers.  This will be done
automatically upon submit, but this command is provided to help with testing
and debugging.
"""

from __future__ import absolute_import, print_function, unicode_literals

import os
from io import open

from fabric.api import env, execute, parallel, prefix, put, puts, run, show, sudo
from fabric.contrib.files import exists
from six import string_types

from .common import (
    add_config,
    add_environment,
    add_name,
    add_options,
    add_override_name,
    add_overwrite_virtualenv,
    add_pool_size,
    add_requirements,
    add_user,
    resolve_options,
)
from ..util import (
    activate_env,
    die,
    get_config,
    get_env_config,
    get_topology_definition,
    get_topology_from_file,
)


def _run_cmd(cmd, user, warn_only=False):
    if user == env.user:
        run(cmd, warn_only=warn_only)
    else:
        sudo(cmd, warn_only=warn_only, user=user)


@parallel
def _create_or_update_virtualenv(
    virtualenv_root,
    virtualenv_name,
    requirements_paths,
    virtualenv_flags=None,
    overwrite_virtualenv=False,
    user="root",
):
    with show("output"):
        virtualenv_path = "/".join((virtualenv_root, virtualenv_name))
        if overwrite_virtualenv:
            puts("Removing virtualenv if it exists in {}".format(virtualenv_root))
            cmd = "rm -rf {}".format(virtualenv_path)
            _run_cmd(cmd, user, warn_only=True)
        if not exists(virtualenv_path):
            if virtualenv_flags is None:
                virtualenv_flags = ""
            puts("virtualenv not found in {}, creating one.".format(virtualenv_root))
            cmd = "virtualenv --never-download {} {}".format(
                virtualenv_path, virtualenv_flags
            )
            _run_cmd(cmd, user)

        if isinstance(requirements_paths, string_types):
            requirements_paths = [requirements_paths]
        temp_req_paths = []
        for requirements_path in requirements_paths:
            puts("Uploading {} to temporary file.".format(requirements_path))
            temp_req = run("mktemp /tmp/streamparse_requirements-XXXXXXXXX.txt")
            temp_req_paths.append(temp_req)
            put(requirements_path, temp_req)

        puts("Updating virtualenv: {}".format(virtualenv_name))
        pip_path = "/".join((virtualenv_path, "bin", "pip"))
        # Make sure we're using latest pip so options work as expected
        run("{} install --upgrade 'pip>=9.0,!=19.0'".format(pip_path), pty=False)
        run(
            (
                "{} install -r {} --exists-action w --upgrade "
                "--upgrade-strategy only-if-needed --progress-bar off"
            ).format(pip_path, " -r ".join(temp_req_paths)),
            pty=False,
        )
        run("rm -f {}".format(" ".join(temp_req_paths)))


def create_or_update_virtualenvs(
    env_name,
    topology_name,
    options,
    virtualenv_name=None,
    requirements_paths=None,
    config_file=None,
    overwrite_virtualenv=False,
    user="root",
):
    """Create or update virtualenvs on remote servers.

    Assumes that virtualenv is on the path of the remote server(s).

    :param env_name: the name of the environment in config.json.
    :param topology_name: the name of the topology (and virtualenv).
    :param virtualenv_name: the name that we should use for the virtualenv, even
                          though the topology file has a different name.
    :param requirements_paths: a list of paths to requirements files to use to
                               create virtualenv
    :param overwrite_virtualenv: Force the creation of a fresh virtualenv, even
                                 if it already exists.
    :param user: Who to delete virtualenvs as when using overwrite_virtualenv
    """
    config = get_config()
    topology_name, topology_file = get_topology_definition(
        topology_name, config_file=config_file
    )
    topology_class = get_topology_from_file(topology_file)
    env_name, env_config = get_env_config(env_name, config_file=config_file)
    if virtualenv_name is None:
        virtualenv_name = topology_name

    config["virtualenv_specs"] = config["virtualenv_specs"].rstrip("/")

    if requirements_paths is None:
        requirements_paths = [
            os.path.join(config["virtualenv_specs"], "{}.txt".format(topology_name))
        ]

    # Check to ensure streamparse is in at least one requirements file
    found_streamparse = False
    for requirements_path in requirements_paths:
        with open(requirements_path, "r") as fp:
            for line in fp:
                if "streamparse" in line:
                    found_streamparse = True
                    break

    if not found_streamparse:
        die(
            "Could not find streamparse in one of your requirements files.  "
            "Checked {}.  streamparse is required for all topologies.".format(
                requirements_paths
            )
        )

    # Setup the fabric env dictionary
    storm_options = resolve_options(options, env_config, topology_class, topology_name)
    activate_env(env_name, storm_options, config_file=config_file)

    # Actually create or update virtualenv on worker nodes
    execute(
        _create_or_update_virtualenv,
        env.virtualenv_root,
        virtualenv_name,
        requirements_paths,
        virtualenv_flags=storm_options.get("virtualenv_flags"),
        hosts=env.storm_workers,
        overwrite_virtualenv=overwrite_virtualenv,
        user=user,
    )


def subparser_hook(subparsers):
    """ Hook to add subparser for this command. """
    subparser = subparsers.add_parser(
        "update_virtualenv", description=__doc__, help=main.__doc__
    )
    subparser.set_defaults(func=main)
    add_config(subparser)
    add_environment(subparser)
    add_overwrite_virtualenv(subparser)
    add_name(subparser)
    add_options(subparser)
    add_override_name(subparser)
    add_pool_size(subparser)
    add_requirements(subparser)
    add_user(subparser)


def main(args):
    """ Create or update a virtualenv on Storm workers. """
    env.pool_size = args.pool_size
    create_or_update_virtualenvs(
        args.environment,
        args.name,
        args.options,
        virtualenv_name=args.override_name,
        requirements_paths=args.requirements,
        config_file=args.config,
        overwrite_virtualenv=args.overwrite_virtualenv,
        user=args.user,
    )
