from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="epub2tts-audio8",
    version="0.1.0",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "epub2tts-audio8=epub2tts_audio8.epub2tts_audio8:main",
        ],
    },
    python_requires=">=3.11",
    author="Christopher Aedo",
    description="Create audiobooks from epub files using Audio8 TTS",
    long_description=open("README.md").read() if __file__ else "",
    long_description_content_type="text/markdown",
)
