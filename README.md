## ontology-toolkit

Maintain version and dependency info in RDF ontologies.

```
$ python ontology-toolkit.py -h
usage: ontology-toolkit.py [-h] [-o {xml,turtle,n3}] {update,export} ...

Ontology toolkit.

positional arguments:
  {update,export}       sub-command help
    update              Update versions and dependencies
    export              Export ontology
    bundle              Bundle ontology for release

optional arguments:
  -h, --help            show this help message and exit
  -o {xml,turtle,n3}, --output-format {xml,turtle,n3}
                        Output format
```

The `update` module modifies ontology version and dependency information
```
$ python ontology-toolkit.py update -h
usage: ontology-toolkit.py update [-h] [-b] [-v SET_VERSION]
                                  [-i [VERSION_INFO]] [-d DEPENDENCY VERSION]
                                  [ontology [ontology ...]]

positional arguments:
  ontology              Ontology file

optional arguments:
  -h, --help            show this help message and exit
  -b, --defined-by      Add rdfs:isDefinedBy to every resource defined.
  -v SET_VERSION, --set-version SET_VERSION
                        Set the version of the defined ontology
  -i [VERSION_INFO], --version-info [VERSION_INFO]
                        Adjust versionInfo, defaults to "Version X.x.x
  -d DEPENDENCY VERSION, --dependency-version DEPENDENCY VERSION
                        Update the import of DEPENDENCY to VERSION
```

The export module will transform the ontology into the desired format, and remove version information, as required by tools such as Top Braid Composer.
```
$ python ontology-toolkit.py export -h
usage: ontology-toolkit.py export [-h] [-s] [ontology [ontology ...]]

positional arguments:
  ontology              Ontology file

optional arguments:
  -h, --help            show this help message and exit
  -m IRI VERSION, --merge IRI VERSION
                        Merge all inputs into a single ontology with the given
                        IRI and version
  -s, --strip-versions  Remove versions from imports.
```

The bundle module is a replacement for the `bundle.bat` script used to version and package [gist](https://github.com/semanticarts/gist)
```
usage: ontology-toolkit.py bundle [-h] [-t TOOLS] [-a ARTIFACTS] [-c CATALOG]
                                  [-o OUTPUT]
                                  version [ontology [ontology ...]]

positional arguments:
  version               Version string to replace X.x.x template
  ontology              Ontology file, directory or name pattern

optional arguments:
  -h, --help            show this help message and exit
  -t TOOLS, --tools TOOLS
                        Location of serializer tool
  -a ARTIFACTS, --artifacts ARTIFACTS
                        Location of release artifacts (release notes, license,
                        etc), defaults to current working directory
  -c CATALOG, --catalog CATALOG
                        Location of Protege catalog, defaults to
                        OntologyFiles/bundle-catalog-v001.xml in the artifacts
                        directory
  -o OUTPUT, --output OUTPUT
                        Output directory for transformed ontology files
```
Defaults are set up such that running `python ontology-toolkit.py bundle <version>` from the `gist` root directory requires no further options