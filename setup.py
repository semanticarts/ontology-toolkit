import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="onto_tool",
    version="0.7.0",
    author="Boris Pelakh",
    author_email="boris.pelakh@semanticarts.com",
    description="Ontology Maintenance and Release Tool",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/semanticarts/ontology-toolkit",
    packages=setuptools.find_packages(),
    install_requires=[
        'rdflib[sparql]>=5.0.0',
        'pydot',
        'jinja2',
        'markdown',
        'mdx_smartypants',
        'pyyaml',
        'jsonschema'
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    package_data={
        'onto_tool': [
            'bundle_schema.json'
        ]
    },
    entry_points={
        "console_scripts": [
            "onto_tool = onto_tool.onto_tool:run_tool"
        ]
    },
    python_requires='>=3.6',
)
