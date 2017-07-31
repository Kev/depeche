#!/usr/bin/env python

# Copyright 2017 Isode Limited
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import print_function

from optparse import OptionParser
import os
from StringIO import StringIO
import json
import hashlib
import subprocess
import shutil

def safeMakeDir(root):
    try:
        if not os.path.exists(root):
            if options.verbose: print("Creating", root)
            os.makedirs(root)
    except Exception as e:
        raise Exception("Couldn't create %s", root)

def removePath(root):
    if 'depeche' not in root:
        print("I don't trust that I'm not going to ruin things, not removing folder without 'depeche' in the name")
        return
    shutil.rmtree(root)

def filenameEncode(contents):
    return hashlib.sha1(contents).hexdigest()

def repositoryCachePath(source):
    return os.path.join(repositories, filenameEncode(source))

def ensureRepository(source):
    path = repositoryCachePath(source)
    if options.verbose: print("Checking for cache of repository", source, "in", path)
    if os.path.exists(path):
        if options.verbose: print("Found")
        return
    if options.verbose: print("Cloning")
    try:
        p = subprocess.check_call(['git', 'clone', "--bare", source, path])
        p = subprocess.check_call(['git', 'config', "remote.origin.fetch", '+refs/heads/*:refs/remotes/origin/*'], cwd=path)
    except (Exception, KeyboardInterrupt) as e:
        try:
            p.terminate()
        except:
            pass
        print("Couldn't clone", source, "into", path, ":", e)
        removePath(path)
        raise e

updatedRepositories = []

def updateRepositoryForPath(path):
    if path in updatedRepositories: return
    updatedRepositories.append(path)
    if options.verbose: print("Updating git repo in",path)
    try:
        p = subprocess.check_call(['git', 'fetch', 'origin'], cwd=path)
    except (Exception, KeyboardInterrupt) as e:
        try:
            p.terminate()
        except:
            pass
        print("Couldn't update", path, ":", e.message)
        raise e


def updateRepository(source):
    path = repositoryCachePath(source)
    if options.verbose: print("Updating", source, "in", path)
    updateRepositoryForPath(path)

def rootPath(sourceKey, version, varsHash):
    return os.path.join(roots, filenameEncode(sourceKey), version, varsHash)

def checkExists(source, sourceKey, version, varsHash):
    path = rootPath(sourceKey, version, varsHash)
    result = os.path.exists(path)
    if options.verbose: print("Checking if", source, "/", version, "exists in", path, ":", result)
    return result

def gitSubTreeCheckout(source, destination, commit, paths=['.'], allowRetry=True):
    if options.verbose: print("Checking out subtree of", source, "in", destination, "version", commit)
    try:
        p = subprocess.check_call(['git', '--work-tree='+destination, 'checkout', commit, '--'] + paths, cwd=source)
    except (Exception, KeyboardInterrupt) as e:
        try:
            p.terminate()
        except:
            pass
        print("Couldn't checkout", source, "into", destination, ":", e.message)
        if allowRetry:
            print("Trying to update repository first")
            updateRepositoryForPath(source)
            gitSubTreeCheckout(source, destination, commit, paths, False)
        else:
            raise e


def buildRepository(source, sourceKey, version, varsHash, varDict, commands):
    path = rootPath(sourceKey, version, varsHash)
    buildPath = os.path.join(tmpDir, filenameEncode(path))
    if options.verbose: print("building", source, "into", path, "using", buildPath)
    if os.path.exists(buildPath):
        print("Path already exists", buildPath)
        raise Exception("Exists")
    safeMakeDir(buildPath)
    cache = repositoryCachePath(source)
    gitSubTreeCheckout(cache, buildPath, version)
    installRoot = varDict['INSTALL_ROOT']
    safeMakeDir(installRoot)
    for commandMap in commands:
        command = commandMap['command']
        commandWords = []
        for word in command:
            for k, v in varDict.items():
                word = word.replace('%%'+k+'%%', v)
            if '%%' in word:
                print("Unsubstituted parameter",word)
                raise Exception("unsubstituted parameter")
            commandWords.append(word)
        env = os.environ.copy()
        env.update(varDict)
        subPath = buildPath
        if 'path' in commandMap:
            subPath = os.path.join(buildPath, commandMap['path'])
        if options.verbose: print("Running:", commandWords, "in", subPath)
        try:
            p = subprocess.check_call(commandWords, env=env, cwd=subPath)
        except (Exception, KeyboardInterrupt) as e:
            try:
                p.terminate()
            except:
                pass
            print("Couldn't run",commandWords,":", e.message)
            removePath(installRoot)
            raise e
    removePath(buildPath)

def serializeDict(thing):
    result = ""
    for key in sorted(thing.keys()):
        result = result + key + '-/-' + thing[key]
    return result

def updateAllRepositories():
    if options.verbose: print("Updating all repositories in",repositories)
    for filename in os.listdir(repositories):
        updateRepositoryForPath(os.path.join(repositories, filename))


class Definition:
    def __init__(self, name, filename, sourceKey, dependencyVersions):
        parsed = self.readFile(filename)
        self.dependencies = []
        self.dependencyVersions = {}
        self.buildSteps = []
        self.neededVariables = []
        self.name = name
        if dependencyVersions:
            self.dependencyVersions = dependencyVersions
        else:
            for k, v in parsed.get('dependencyVersions', {}).items():
                self.dependencyVersions[k] = v
        for dependency in parsed.get('dependencies', []):
            self.populateDependency(dependency)
        for buildStep in parsed.get('buildSteps', []):
            self.buildSteps.append(buildStep)
        for variable in parsed.get('variables', []):
            self.neededVariables.append(variable)
        self.source = parsed.get('source', sourceKey)
        self.sourceKey = sourceKey

    def install(self):
        if options.verbose: print("Checking for", self.source)
        for dependency in self.dependencies:
            dependency.install()
        if self.sourceKey:
            # if not the product itself
            varDict = self.calculateVariables()
            varDict['FULL_INSTALL'] = "True"
            varsHash = filenameEncode(serializeDict(varDict))
            version = self.dependencyVersions.get(self.source, None)
            if options.verbose: print("Rootpath constructing:", self.sourceKey, version, varsHash)
            self.root = rootPath(self.sourceKey, version, varsHash)
            ensureRepository(self.source)
            varDict['INSTALL_ROOT'] = self.root
            if not version:
                print("No version defined for", self.source)
                raise Exception("No version defined")
            if not checkExists(self.source, self.sourceKey, version, varsHash):
                buildRepository(self.source, self.sourceKey, version, varsHash, varDict, self.buildSteps)

    def calculateVariables(self):
        possibleVars = {}
        result = self.dependencyRoots()
        for key in self.neededVariables:
            result[key] = possibleVars[key]
        return result

    def populateDependency(self, dependency):
        sourceType = dependency.get("sourceType", "git")
        source = dependency.get("source", "")
        name = dependency["name"]
        if sourceType == "file":
            self.populateFileDependency(name, source)
        elif sourceType == "git":
             self.populateGitDependency(name, source, self.dependencyVersions[source])
        else:
            raise Exception("Invalid source type %s for %s", sourceType, source)

    def populateGitDependency(self, name, source, commit):
        ensureRepository(source)
        cachedDepecheDir = os.path.join(roots, filenameEncode(source), commit)
        safeMakeDir(cachedDepecheDir)
        cachedDepecheFile = os.path.join(cachedDepecheDir, 'depeche.json')
        if not os.path.exists(cachedDepecheFile):
            gitSubTreeCheckout(repositoryCachePath(source), cachedDepecheDir, commit, ['depeche.json'])
        self.dependencies.append(Definition(name, cachedDepecheFile, source, self.dependencyVersions))

    def populateFileDependency(self, name, filename):
        try:
            with open(filename, 'r') as f:
                contents = f.read()
                f.close()
        except Exception as e:
            raise Exception("Couldn't read dependency file from %s" % filename)

        # FIXME: replace with something shorter
        encoding = filenameEncode(contents)
        root = os.path.join(roots, encoding)
        safeMakeDir(root)

        cachedFilename = os.path.join(root, "depeche.json")
        if not os.path.exists(cachedFilename):
            try:
                f = open(cachedFilename, 'w')
                f.write(contents)
                f.close()
            except Exception as e:
                raise Exception("Couldn't cache dependency file from %s to %s" % filename, cachedFilename)
        self.dependencies.append(Definition(name, cachedFilename, encoding, self.dependencyVersions))

    def readFile(self, filename):
        if options.verbose: print("Loading dependency file", filename)
        #TODO try:
        #     with open(filename, 'r') as f:
        #         parsed = json.load(f)
        # except Exception as e:
        #     raise Exception("Couldn't read dependency file from %s" % cachedDepecheFile)

        try:
            f = open(filename, 'r')
            dependenciesJSON = f.read()
        except Exception as e:
            # if options.debug:
            #     raise
            raise Exception("Couldn't read dependency file from %s" % filename)
        f.close()
        try:
            dependencies = json.load(StringIO(dependenciesJSON))
        except Exception as e:
            # if options.debug:
            #     raise
            raise Exception("Invalid dependencies json in %s: %s" % (filename, e.message))
        return dependencies

    def dependencyRoots(self):
        roots = {}
        for dependency in self.dependencies:
            roots[dependency.name.upper()+'_ROOT'] = dependency.root
        return roots

    def writeCMakeFile(self, cmakeFile):
        try:
            f = open(cmakeFile, 'w')
            for k,v in self.dependencyRoots().items():
                f.write("SET(" + k + " " + v + ")\n")
            for k,v in self.dependencyRoots().items():
                f.write("list(INSERT CMAKE_MODULE_PATH 0 '" + v + "')\n")
            f.close()
        except Exception as e:
            raise Exception("Couldn't write cmake file %s, %s" % (cmakeFile, e.message))

parser = OptionParser()
parser.add_option("-f", "--file", dest="dependenciesFile", help="path to the depeche.json file", default="depeche.json")
parser.add_option("-c", "--cmake-file", dest="cmakeFile", help="path to the cmake file to produce", default="CMakeLists-depeche.txt")
parser.add_option("-v", "--verbose", dest="verbose", action="store_true", help="Print extra output", default=True)
parser.add_option("-q", "--quiet", dest="verbose", action="store_false", help="Don't print output")
parser.add_option("-m", "--master", dest="master", action="store_true", help="Update all cached repositories", default=False)
(options, args) = parser.parse_args()

depecheHome = os.getenv("DEPECHE_HOME", os.path.expanduser("~/.depeche"))
if options.verbose: print("Fetching dependencies from", options.dependenciesFile, "with DEPECHE_HOME", depecheHome)
repositories = os.path.join(depecheHome, "repositories") # global
roots = os.path.join(depecheHome, "roots") # global
tmpDir = os.path.join(depecheHome, "tmp") # global
try:
    if not os.path.exists(repositories):
        if options.verbose: print("Creating", repositories)
        os.makedirs(repositories)
except Exception as e:
    print("Failed creating or testing", repositories)
try:
    if not os.path.exists(roots):
        if options.verbose: print("Creating", roots)
        os.makedirs(roots)
except Exception as e:
    print("Failed creating or testing", roots)
try:
    if not os.path.exists(tmpDir):
        if options.verbose: print("Creating", tmpDir)
        os.makedirs(tmpDir)
except Exception as e:
    print("Failed creating or testing", tmpDir)

if options.master:
    updateAllRepositories()

defs = Definition("root project", options.dependenciesFile, None, None)
defs.install()
defs.writeCMakeFile(options.cmakeFile)
