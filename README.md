# Depeche (Dependency Fetcher)

Versioned dependency cacheing

## Usage

### Building a project using depeche

Building a project with depeche should be transparent, other than needing to have `depeche.py` in your $PATH, and the build system (typically cmake) will then call out to depeche.

### Running depeche manually

If you want to run depeche manually, just ensure you're in the folder of your project that contains `depeche.json`, and run `depeche.py` (the usual `--help` exists). If the dependencies for the project already exist this should exit silently and if they don't this should install them (and subsequent runs would then exit silently (and pretty much immediately)).


### Integrating depeche with cmake

Near the top of your project's root CMakeLists.txt, put

```
execute_process(COMMAND "depeche.py" WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
configure_file(depeche.json ignore.txt)
include(CMakeLists-depeche.txt)
```

The first line calls depeche, which will spit out CMakeLists-depeche.txt. The second line forces a configure-time dependency on depeche.json, which ensures cmake will be ru-run (and in turn so will depeche) whenever the depeche dependencies change - so you should never need to re-run depeche manually (you probably want to .gitignore ignore.txt). The last line then pulls in the generated file, which contains the install paths for all the dependencies. If you want to use the installed cmake find modules, something like:
```
set(CMAKE_MODULE_PATH "${OPENSSL_ROOT}")
find_package(OpenSSL REQUIRED)
```
should do the trick (`OPENSSL_ROOT` is defined as part of CMakeLists-depeche.txt if you have a dependency named 'Openssl' (caps don't matter)).

### Writing a depeche.json for your project

Your project's depeche.json only defines dependencies and their versions (i.e. doesn't say how to build the current project). Something like:
```
{
    "dependencies": [
        {"sourceType": "git", "source": "ssh://gitserver/openssl.git", "name": "openssl"},
        {"sourceType": "git", "source": "ssh://gitserver/googletest.git", "name": "gtest"},
        {"sourceType": "git", "source": "ssh://gitserver/boost.git", "name": "boost"},
        {"sourceType": "git", "source": "ssh://gitserver/swift.git", "name": "swift"}
    ],
    "dependencyVersions": {
        "ssh://gitserver/openssl.git": "cae837b7d4458adf2da884d57175031a5102429c",
        "ssh://gitserver/cmake.git": "a17d4c940075061c0405029439b08a672c10fd62",
        "ssh://gitserver/googletest.git": "bf6978b71d48ae44323a186a7776ffd5378639a2",
        "ssh://gitserver/boost.git": "8145342e907febfce70d5f83d3971943ba918e43",
        "ssh://gitserver/swift.git": "131fb4180c3d616e5f1c82e8377d2e07968be572"
    }
}
```

### Writing depeche.json for a dependency
Conversely, the depeche.json for a dependency repository has to say how it's built, and its dependencies, but not their versions. The versions of dependencies (including indirect dependencies) must be defined by the project.
```
{
	"dependencies": [
		{"sourceType": "git", "source": "ssh://gitserver/cmake.git", "name": "cmake"}
	],
	"buildSteps": [
		{"command": ["%%CMAKE_ROOT%%/build.sh", "newbuild"]},
		{"command": ["%%CMAKE_ROOT%%/build.sh", "install"]},
		{"command": ["cp", "-r", "include", "%%INSTALL_ROOT%%/"]}
	]
}
```
This gives the three commands that are run when building the dependency, and says it depends on the cmake repository. %%INSTALL_ROOT%% is the path into which this dependency must install. In this example, %%CMAKE_ROOT%% is also used - this is the install root of the dependency with name 'cmake', and is only defined because this dependency itself depends on cmake.git.

## How it works

### Dependency definitions

Dependencies are defined in `depeche.json` files. This lists the dependencies, their versions (in the case of the top level project/product) and the build steps (in the case of dependency repositories). The versions all come from the top level `depeche.json`

### The version block

The `dependencyVersions` block is only present in the top level project not in the dependencies. Every dependency, whether explicit (from the top level project) or implicit (pulled in from a dependency) must have a version defined in the `dependencyVersions` block, even though implicit dependencies will not have an entry in the top level `dependencies` block (this is one of the reasons the blocks are split). These versions are then inherited by all dependencies built (and the versions of the dependencies used by a particular dependency form part of the hash of the build flags for that dependency, ensuring things are rebuilt when their explicit or implicit dependencies change). In this way, everyone building a particular version of a project will have it use an identical set of dependency versions.

### Storage structure

By default all depeche data are stored in ~/.depeche; to store them elsewhere set the $DEPECHE_HOME variable to point somewhere else. Note that the path must contain the string 'depeche' somewhere - dpeche itself won't clean up any paths without that string in them, to prevent bugs accidentally nuking a filesystem (I don't trust myself). Under the depeche home are three folders, `repositories`, `roots` and `tmp`.
* `tmp` is only used for building.
* `roots` holds all the install trees for dependencies.
* `repositories` holds bare clones of every dependency used.

Depeche stores dependencies in the install path in a hierachy of hash('dependency repository') / hash('dependency version') / hash('build flags'). These are standard install trees, /include, /lib, etc. The build tree is removed once installed; include files etc. must be installed, they can't be read out of the source tree.

### Updating repositories
All repositories are cached so installs of future versions of that dependency will be faster (and offline operation is possible after the initial clone). Depeche won't hit the network unless it's either run with the `-m` switch, in which case it'll try to fetch into every cached repo it has, or if it tries to check the required version out of the cache and finds it's not available. As such for disconnected operation it's sensible to run `depeche -m` every so often to ensure all versions of dependencies are available - this won't clone any dependencies that have not previously been used, though.
