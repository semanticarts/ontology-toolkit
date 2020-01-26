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
