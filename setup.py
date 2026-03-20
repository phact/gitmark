from setuptools import setup, find_packages

setup(
    name="gitmark",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "colorama>=0.4.6",
    ],
    entry_points={
        "console_scripts": [
            "gitmark=gitmark.main:main",
        ],
    },
    python_requires=">=3.8",
)
