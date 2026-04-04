from setuptools import setup

setup(
    name="kiro-sessionizer",
    version="0.1.0",
    author="Blake Smith",
    author_email="Blakeinvictoria@gmail.com",
    py_modules=["kiro_sessionizer"],
    scripts=["kiro-sessionizer"],
    entry_points={
        "console_scripts": [
            "kiro_sessionizer=kiro_sessionizer:main",
        ],
    },
)
