from setuptools import setup, find_packages

setup(
    name="cell-ontology-mapper",
    version="1.0.0",
    description="MCP server for mapping cell surface markers to Cell Ontology terms",
    author="SOULCAP Cell Mapping Agent",
    packages=find_packages(),
    install_requires=[
        "mcp>=1.0.0",
        "pydantic>=2.0.0",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "cell-ontology-mapper=mcp_server:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)