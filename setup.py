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
        'pyparsing>=3.1.0',
        'rdflib>=7.0.0',
        'pydot>=4.0.1',
        'jinja2>=3.1.6',
        'markdown2>=2.5.5',
        'pygments>=2.21.0',
        'pyyaml>=6.0.3',
        'requests>=2.34.2',
        'jsonschema>=3.2.0',
        'SPARQLWrapper~=1.8.4',
        'pyshacl~=0.19.0'
    ],
    tests_require=[
        'pytest~=9.2.0',
        'pytest-cov~=7.1.0'
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
    python_requires='>=3.11',
)
