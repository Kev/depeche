#!/usr/bin/env python

# Copyright 2017 Isode Limited
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import print_function

from optparse import OptionParser
import os
import json
import hashlib
import logging
import subprocess
import shutil

def safeMakeDir(root):
    try:
        if not os.path.exists(root):
            logging.debug("Creating %s", root)
            os.makedirs(root)
    except Exception as e:
        raise Exception("Couldn't create %s", root)

def removePath(root):
    if 'depeche' not in root:
        logging.error("I don't trust that I'm not going to ruin things, not removing folder without 'depeche' in the name")
        return
    logging.info("Removing directory %s", root)
    shutil.rmtree(root)

def filenameEncode(contents):
    return hashlib.sha1(contents.encode("utf-8")).hexdigest()

def repositoryCachePath(source):
    return os.path.join(repositories, filenameEncode(source))

def repositoryWorkingPath(source):
    return os.path.join(workings, filenameEncode(source))

def ensureRepository(source):
    cachePath = repositoryCachePath(source)
    workPath = repositoryWorkingPath(source)
    logging.debug("Checking for cache of repository %s in %s", source, cachePath)
    if os.path.exists(cachePath):
        try:
            p = subprocess.check_call(['git', 'fetch', "work"], cwd=cachePath)
        except (Exception, KeyboardInterrupt) as e:
            try:
                p.terminate()
            except:
                pass
            logging.error("Couldn't fetch working checkout for %s, %s: %s", source, cachePath, e)
        logging.debug("Found")
        return
    logging.debug("Cloning " + source)
    try:
        p = subprocess.check_call(['git', 'clone', "--bare", source, cachePath])
        p = subprocess.check_call(['git', 'config', "remote.origin.fetch", '+refs/heads/*:refs/remotes/origin/*'], cwd=cachePath)
        p = subprocess.check_call(['git', 'clone', source, workPath])
        p = subprocess.check_call(['git', 'remote', "add", 'work', workPath], cwd=cachePath)
    except (Exception, KeyboardInterrupt) as e:
        try:
            p.terminate()
        except:
            pass
        logging.error("Couldn't clone %s into %s: %s", source, cachePath, e)
        removePath(cachePath)
        removePath(workPath)
        raise e

updatedRepositories = []

def updateRepositoryForPath(path):
    if path in updatedRepositories: return
    updatedRepositories.append(path)
    logging.debug("Updating git repo in %s", path)
    try:
        p = subprocess.check_call(['git', 'fetch', 'origin'], cwd=path)
    except (Exception, KeyboardInterrupt) as e:
        try:
            p.terminate()
        except:
            pass
        logging.error("Couldn't update %s: %s", path, e)
        raise e


def updateRepository(source):
    path = repositoryCachePath(source)
    logging.debug("Updating %s in %s", source, path)
    updateRepositoryForPath(path)

def rootPath(sourceKey, version, varsHash):
    return os.path.join(roots, filenameEncode(sourceKey), version, varsHash)

def checkExists(source, sourceKey, version, varsHash):
    path = rootPath(sourceKey, version, varsHash)
    result = os.path.exists(path)
    logging.debug("Checking if %s/%s exists in  %s: %s", source, version, path, result)
    return result

def gitSubTreeCheckout(source, destination, commit, paths=['.'], allowRetry=True):
    logging.debug("Checking out subtree of %s in %s version %s", source, destination, commit)
    try:
        p = subprocess.check_call(['git', '--work-tree='+destination, 'checkout', commit, '--'] + paths, cwd=source)
    except (Exception, KeyboardInterrupt) as e:
        try:
            p.terminate()
        except:
            pass
        logging.error("Couldn't checkout %s into %s: %s", source, destination, e)
        if allowRetry:
            logging.info("Trying to update repository first")
            updateRepositoryForPath(source)
            gitSubTreeCheckout(source, destination, commit, paths, False)
        else:
            removePath(destination)
            raise e


def buildRepository(source, sourceKey, version, varsHash, varDict, commands):
    path = rootPath(sourceKey, version, varsHash)
    buildPath = os.path.join(tmpDir, filenameEncode(path))
    logging.debug("building %s into %s using %s", source, path, buildPath)
    logging.debug("Variables: %s", varDict)
    if os.path.exists(buildPath):
        if options.keep:
            logging.error("Path already exists: %s", buildPath)
            raise Exception("Exists")
        else:
            removePath(buildPath)
    safeMakeDir(buildPath)
    cache = repositoryCachePath(source)
    gitSubTreeCheckout(cache, buildPath, version)
    installRoot = varDict['INSTALL_ROOT']
    safeMakeDir(installRoot)

    commandsToExecute = []
    for commandMap in commands:
        if 'command' in commandMap:
            commandsToExecute.append(commandMap)
        elif 'commands' in commandMap:
            if 'condition' in commandMap:
                if eval(commandMap['condition'], {'__builtin__':None}, varDict):
                    for command in commandMap['commands']:
                        commandsToExecute.append(command)
                else:
                    logging.debug("Commands condition '%s' failed for commmands '%s'.", commandMap['condition'], commandMap['commands'])
        else:
            logging.error("Unsupported buildSteps value.")
            raise Exception("Unsupported buildSteps value.")

    for command in commandsToExecute:
        commandWords = []
        for word in command['command']:
            for k, v in varDict.items():
                word = word.replace('%%'+k+'%%', v)
            if '%%' in word:
                logging.error("Unsubstituted parameter %s", word)
                raise Exception("unsubstituted parameter")
            commandWords.append(word)
        env = os.environ.copy()
        env.update(varDict)
        subPath = buildPath
        if 'path' in command:
            subPath = os.path.join(buildPath, command['path'])
        logging.debug("Running: %s in %s", commandWords, subPath)
        try:
            p = subprocess.check_call(commandWords, env=env, cwd=subPath)
        except (Exception, KeyboardInterrupt) as e:
            try:
                p.terminate()
            except:
                pass
            logging.error("Couldn't run %s: %s", commandWords, e)
            logging.error("Was running in %s", buildPath)
            removePath(installRoot)
            raise e
    removePath(buildPath)

def serializeDict(thing):
    result = ""
    for key in sorted(thing.keys()):
        result = result + key + '-/-' + thing[key]
    return result

def updateAllRepositories():
    logging.debug("Updating all repositories in %s", repositories)
    for filename in os.listdir(repositories):
        updateRepositoryForPath(os.path.join(repositories, filename))


class Definition:
    def __init__(self, name, depecheFilename, depecheVarFilename, sourceKey, dependencyVersions):
        self.dependencies = []
        self.dependencyVersions = {}
        self.buildSteps = []
        self.neededVariables = []
        self.name = name
        self.depecheVarFilename = depecheVarFilename
        self.depecheVars = {}
        parsed = self.readFile(depecheFilename)
        if depecheVarFilename:
            self.depecheVars = self.readFile(depecheVarFilename)

        if dependencyVersions:
            self.dependencyVersions = dependencyVersions
        else:
            for k, v in parsed.get('dependencyVersions', {}).items():
                self.dependencyVersions[k] = v
        for dependency in parsed.get('dependencies', []):
            self.populateDependency(dependency)
        for buildStep in parsed.get('buildSteps', []):
            self.buildSteps.append(buildStep)
        for variable in parsed.get('neededVariables', []):
            self.neededVariables.append(variable)
        self.source = parsed.get('source', sourceKey)
        self.sourceKey = sourceKey

    def install(self):
        logging.debug("Checking for %s", self.source)
        for dependency in self.dependencies:
            dependency.install()
        if self.sourceKey:
            # if not the product itself
            varDict = self.calculateVariables()
            varDict['FULL_INSTALL'] = "True"
            varsHash = filenameEncode(serializeDict(varDict))
            version = self.dependencyVersions.get(self.source, None)
            logging.debug("Rootpath constructing: %s %s %s", self.sourceKey, version, varsHash)
            self.root = rootPath(self.sourceKey, version, varsHash)
            ensureRepository(self.source)
            varDict['INSTALL_ROOT'] = self.root
            if not version:
                logging.error("No version defined for %s", self.source)
                raise Exception("No version defined")
            if not checkExists(self.source, self.sourceKey, version, varsHash):
                logging.info("Building %s", self.name)
                buildRepository(self.source, self.sourceKey, version, varsHash, varDict, self.buildSteps)

    def calculateVariables(self):
        possibleVars = self.depecheVars
        result = self.dependencyRoots()
        for key in self.neededVariables:
            if key in possibleVars:
                result[key] = possibleVars[key]
            else:
                logging.error("Missing variable '%s'. Please check depeche-var.json.", key)
                raise Exception("Missing variable '%s'. Please check depeche-var.json.", key)
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
        self.dependencies.append(Definition(name, cachedDepecheFile, self.depecheVarFilename, source, self.dependencyVersions))

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
        self.dependencies.append(Definition(name, cachedFilename, self.depecheVarFilename, encoding, self.dependencyVersions))

    def readFile(self, filename):
        logging.debug("Loading JSON file %s", filename)
        try:
            with open(filename) as f:
                return json.load(f)
        except Exception as e:
            raise Exception("Invalid JSON in %s %s: %s" % (self.name, filename, e))

    def dependencyRoots(self):
        roots = {}
        for dependency in self.dependencies:
            roots[dependency.name.upper()+'_ROOT'] = dependency.root
        return roots

    def writeCMakeFile(self, cmakeFile):
        try:
            dependencies = self.dependencyRoots().items()
            # Move dependency with CMAKE in its name (e.g. for cmake.git) to the front,
            # so it is preprended first and ends last in the list of CMAKE_MODULE_PATH
            cmakeValue = next((x for x in dependencies if "CMAKE" in x[0]), None)
            if cmakeValue:
                cmakeValueIndex = dependencies.index(cmakeValue)
                dependencies.insert(0, dependencies.pop(cmakeValueIndex))
            f = open(cmakeFile, 'w')
            for k,v in dependencies:
                f.write("SET(" + k + " " + v + ")\n")
            for k,v in dependencies:
                f.write("list(INSERT CMAKE_MODULE_PATH 0 \"" + v + "\")\n")
            f.close()
        except Exception as e:
            raise Exception("Couldn't write cmake file %s, %s" % (cmakeFile, e))

parser = OptionParser()
parser.add_option("-f", "--file", dest="dependenciesFile", help="path to the depeche.json file", default="depeche.json")
parser.add_option("-c", "--cmake-file", dest="cmakeFile", help="path to the cmake file to produce", default="CMakeLists-depeche.txt")
parser.add_option("-e", "--environment", dest="variables", help="path to the depeche-var.json file, defining config variables used by depeche")
parser.add_option("-v", "--verbose", dest="loglevel", action="store_const", const=logging.DEBUG, help="Print extra output")
parser.add_option("-q", "--quiet", dest="loglevel", action="store_const", const=logging.ERROR, help="Don't print output")
parser.add_option("-m", "--master", dest="master", action="store_true", help="Update all cached repositories", default=False)
parser.add_option("-k", "--keep", dest="keep", action="store_true", help="Don't replace existing temporary trees (if previous compilation failed)", default=False)
parser.add_option("", "--cache_dir", dest="cacheDir", help="Path storing the repository", default=None)
parser.add_option("-w", "--work_dir", dest="workDir", help="Path storing the working checkout of the repository", default=None)
parser.set_defaults(loglevel=logging.INFO)
(options, args) = parser.parse_args()

logging.basicConfig(format="%(message)s", level=options.loglevel)


depecheHome = os.getenv("DEPECHE_HOME", os.path.expanduser("~/.depeche"))
logging.debug("Fetching dependencies from %s with DEPECHE_HOME %s", options.dependenciesFile, depecheHome)
repositories = os.path.join(depecheHome, "repositories") # global
workings = os.path.join(depecheHome, "work") # global
roots = os.path.join(depecheHome, "roots") # global
tmpDir = os.path.join(depecheHome, "tmp") # global

try:
    if not os.path.exists(repositories):
        logging.debug("Creating", repositories)
        os.makedirs(repositories)
except Exception as e:
    logging.error("Failed creating or testing %s", repositories)
try:
    if not os.path.exists(workings):
        logging.debug("Creating", workings)
        os.makedirs(workings)
except Exception as e:
    logging.error("Failed creating or testing", workings)
try:
    if not os.path.exists(roots):
        logging.debug("Creating", roots)
        os.makedirs(roots)
except Exception as e:
    logging.error("Failed creating or testing %s", roots)
try:
    if not os.path.exists(tmpDir):
        logging.debug("Creating", tmpDir)
        os.makedirs(tmpDir)
except Exception as e:
    logging.error("Failed creating or testing %s", tmpDir)

if options.master:
    updateAllRepositories()

run = True

if options.cacheDir:
    print("Repository " + options.cacheDir + " will be cached at " + repositoryCachePath(options.cacheDir))
    run = False

if options.workDir:
    print("Repository " + options.workDir + " will have a working copy at " + repositoryWorkingPath(options.workDir))
    run = False

if run:
    defs = Definition("root project", options.dependenciesFile, options.variables, None, None)
    defs.install()
    defs.writeCMakeFile(options.cmakeFile)
