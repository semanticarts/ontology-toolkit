import setuptools

from onto_tool import VERSION

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="onto_tool",
    version=VERSION,
    author="Boris Pelakh",
    author_email="boris.pelakh@semanticarts.com",
    description="Ontology Maintenance and Release Tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/semanticarts/ontology-toolkit",
    packages=setuptools.find_packages(),
    install_requires=[
        'pyparsing',
        'rdflib==7.0.0',
        'pydot',
        'jinja2',
        'markdown2',
        'pyyaml==5.4',
        'jsonschema==3.2.0',
        'SPARQLWrapper==1.8.4',
        'pyshacl==0.19.0'
    ],
    tests_require=[
        'pytest',
        'pytest-cov'
    ],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    package_data={
        'onto_tool': [
            'bundle_schema.yaml'
        ]
    },
    entry_points={
        "console_scripts": [
            "onto_tool = onto_tool.onto_tool:run_tool"
        ]
    },
    python_requires='>=3.8',
)
