from setuptools import setup
from importlib.machinery import SourceFileLoader

with open('README.md') as file:
    long_description = file.read()

name='musclesinaction'
version = SourceFileLoader(name + '.version', name + '/version.py').load_module()

setup(
   name=name,
   version=version.version,
   description='Package for Muscles in Action',
   author='Mia Chiquier, Carl Vondrick',
   author_email='mac2500@columbia.edu',
   url='TBD',
   packages=[name],
   long_description=long_description,
   long_description_content_type='text/markdown',
   keywords='musclesinaction',
   license='',
   install_requires=[],
)
