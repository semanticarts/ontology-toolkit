# ontology-toolkit

Maintain version and dependency info in RDF ontologies.

## Installation

To install the toolkit, run `pip install .` from the root directory, which
will install the `onto_tool` command and all its dependencies into your environment.

```
$ onto_tool -h
usage: onto_tool [-h] {update,export,bundle,graphic} ...

Ontology toolkit.

positional arguments:
  {update,export,bundle,graphic}
                        sub-command help
    update              Update versions and dependencies
    export              Export ontology
    bundle              Bundle ontology for release
    graphic             Create PNG graphic and dot file from OWL files

optional arguments:
  -h, --help            show this help message and exit
```

## Sub-Commands

### Update

The `update` sub-command modifies ontology version and dependency information
```
$ onto_tool update -h
usage: onto_tool update [-h] [-b] [-v SET_VERSION]
                        [-i [VERSION_INFO]] [-d DEPENDENCY VERSION]
                        [ontology [ontology ...]]

positional arguments:
  ontology              Ontology file or directory containing OWL files.

optional arguments:
  -h, --help            show this help message and exit
  -b, --defined-by      Add rdfs:isDefinedBy to every resource defined.
  -v SET_VERSION, --set-version SET_VERSION
                        Set the version of the defined ontology
  -i [VERSION_INFO], --version-info [VERSION_INFO]
                        Adjust versionInfo, defaults to "Version X.x.x
  -d DEPENDENCY VERSION, --dependency-version DEPENDENCY VERSION
                        Update the import of DEPENDENCY to VERSION
  -o {xml,turtle,nt}, --output-format {xml,turtle,nt}
                        Output format
```

### Export

The `export` sub-command will transform the ontology into the desired format, and remove version information, as required by tools such as Top Braid Composer.
```
$ onto_tool export -h
usage: onto_tool export [-h] [-o {xml,turtle,nt} | -c CONTEXT] [-s]
                        [-m IRI VERSION]
                        [ontology [ontology ...]]

positional arguments:
  ontology              Ontology file or directory containing OWL files

optional arguments:
  -h, --help            show this help message and exit
  -o {xml,turtle,nt}, --output-format {xml,turtle,nt}
                        Output format
  -c CONTEXT, --context CONTEXT
                        Export as N-Quads in CONTEXT.
  -s, --strip-versions  Remove versions from imports.
  -m IRI VERSION, --merge IRI VERSION
                        Merge all inputs into a single ontology with the given
                        IRI and version
```

### Graphic

The `graphic` sub-command will create either a comprehensive diagram showing ontology modules together with classes, object properties and "Things" together with the path of imports, or (if the 'wee' option is selected) a simple diagram of ontology modules and the import hierarchy.  Graphics are exported both as ```png``` files and also as a ```dot``` file.  This ```dot``` file can be used with Graphviz or with web tools such as [Model Viewer](http://www.semantechs.co.uk/model-viewer)

```
$ onto_tool graphic -h
usage: onto_tool graphic [-h] [-o OUTPUT] [-v VERSION] [-w]
                         [ontology [ontology ...]]

positional arguments:
  ontology              Ontology file, directory or name pattern

optional arguments:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output directory for generated graphics
  -v VERSION, --version VERSION
                        Version to place in graphic
  -w, --wee             a version of the graphic with only core information
                        about ontology and imports
```

### Bundle

The `bundle` sub-command supports creating an ontology deployment containing both RDF and non-RDF artifacts for delivery or web hosting.

```
$ onto_tool bundle -h
usage: onto_tool bundle [-h] [-v VARIABLE VALUE] bundle

positional arguments:
  bundle                JSON or YAML bundle definition

optional arguments:
  -h, --help            show this help message and exit
  -v VARIABLE VALUE, --variable VARIABLE VALUE
                        Set value of VARIABLE to VALUE
```

The bundle definition is either YAML or JSON, and contains the following sections:

#### Variable definition

```yaml
variables:
  name: "gist"
  version: "X.x.x"
  input: "."
  rdf-toolkit: "{input}/tools/rdf-toolkit.jar"
  output: "{name}{version}_webDownload"
```
Variables are initialized with the default values provided, but can be overriden via the `--variable` command line option.
Values can reference other values using the `{name}` template syntax.

#### Tool definition

```yaml
tools:
- name: "serializer"
  type: "Java"
  jar: "{rdf-toolkit}"
  arguments:
    - "-tfmt"
    - "rdf-xml"
    - "-sdt"
    - "explicit"
    - "-dtd"
    - "-ibn"
    - "-s"
    - "{inputFile}"
    - "-t"
    - "{outputFile}"
```
At this time, only Java tools can be defined, and they require a `name` by which they are referenced, 
a path to the executable Jar file and a list of `arguments` that will be applied to each file processed.
The `inputFile` and `outputFile` variables will be bound during execution, but other variables can be
used to construct the arguments.

#### Actions

Actions are executed in the order they are listed. Each action must have an `action` attribute, which can be 
one of the following values:
- `mkdir`, which requires a `directory` attribute to specify the path of the directory to be created 
  (only if it doesn't already exist)
- `copy`, which copies files into the bundle, and supports the following arguments:
  - `source`, `target` and `includes` - if `includes` is not present, `source` and `target` are both
    assumed to be file paths to a single file. If `includes` is provided, `source` and `target` are 
    assumed to be directories, and each member of the `includes` list a glob pattern inside the
    `source` directory.
  - `rename` - If provided, must contain `from` and `to` attributes. When specified, each file
    is renamed as it is copied, where `from` is treated as a Python regular expression
    applied to the base name of the source file, and `to` is the substitution string which
    replaces it in the name of the target file. Backreferences are available for capturing groups, e.g.
    ```yaml
      rename:
        from: "(.*)\\.owl"
        to: "\\g<1>{version}.owl"
    ```
    will add a version number to the base name of each `.owl` file. Further documentation on
    Python regular expression replace functionality can be found
    [here](https://docs.python.org/3/howto/regex.html#search-and-replace).
  - `replace` - If provided, must contain `from` and `to` attributes. When specified, each file
    is processed after being copied, and each instance of the `from` pattern is replaced
    with `to` string in the file contents. Python regular expression syntax and backreferences are
    supported as shown in the `rename` documentation.
- `move`, which moves files according the provided options, which are identical to the ones supported
  by `copy`.
- `definedBy`, which inspects each input file to identify a single defined ontology, and then
  adds a `rdfs:isDefinedBy` property to every `owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`
  and `owl:AnnotationProperty` defined in the file referencing the identified ontology. Existing
  `rdfs:isDefinedBy` values are removed prior to the addition. Input and output file specification
  options are identical to those used by the `copy` action.
- `transform`, which applies the specified tool to a set of input files, and supports the following
  arguments:
  - `tool`, which references the `name` of a tool which must be defined in the `tools` section.
  - `source`, `target` and `includes`, which function just like they do for the `copy` and `move`
    actions, with each input and output path bound into the `inputFile` and `outputFile` variables
    before the tool arguments are interpreted.
  - `replace` and `rename`, which are applied after the tool invocation, and work as described above.
- `markdown` transforms a `.md` file referenced in `source` into an HTML output specified in `target`.
- `graph` reads RDF files provided via the `source` and `includes` options and generates a graphical
  representation of the ontology, as in the `graphic` sub-command described above. Both `.dot` and
  `.png` outputs are written to the directory specified in the `target` option, and `title` and 
  `version` attributes configure the title on the generated graph. If `compact` is specified as
  `True`, a concise graph including only ontology names and imports is generated.