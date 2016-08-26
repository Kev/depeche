# Depeche (Dependency Fetcher)

Versioned dependency cacheing

## Usage
```
./depeche.py --file=[dependencies.json] --install=[INSTALL PATH] --work=[WORKING PATH] --options=[COMPILER OPTIONS STRING]
```
The parameters default to
--file ./depeche.json
--install $HOME/.depeche/install
--work $HOME/.depeche/work

The compiler options uniquely identify the compiler options used, and must differ when builds aren't reusable (e.g. between debug and release)

## How it works

### Dependency definitions

Dependencies are defined in `depeche.json` files. These list the 

Note that for the dependency repositories, the versions of their recursive dependencies are ignored, and must be supplied by the owning project.

```
[
	{name='swift', uri='ssh:/...', commit='tag0.0.1'},
	{name='openssl, url='ssh...', commit='ac283f2b'}	
]
```

### Storage structure

Depeche stores dependencies in the install path in a hierachy of 'dependency repository' / 'calculated dependency version'. These are standard install trees, /include, /lib, etc.

### Dependency repository hash
The dependency repository is an unseeded sha1, base64d, of the URI.
```
base64(sha(URI))
```

### Dependency version hash
The version is calculated by taking the version of the dependency, concaterating any necessary configuration options (e.g. release, debug) then for each dependency of the dependency (recursively) concatenating the repository hash and the version.
Example: if swift depends on boost, openssl and libxml, boost depends on openssl, and we're building for release and using version A, B, C, D of these respectively (and assuming that the URIs of boost, libxml and openssl sort in that order):
```
swiftversion = base64(sha(A + "release" + boostURI + base64(sha(B + opensslURI + C)) + libxmlURI + base64(sha(D)) + opensslURI + base64(sha(C))))
```

