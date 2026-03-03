from setuptools import setup, find_packages

setup(
   name='auto_proxy_vpn',
   version='0.0.1',
   author='Ignasi Rovira',
   packages=find_packages(),
   python_requires='>=3.9',
   install_requires=['requests'],
   description='A package to create on demand proxies and vpns in different cloud providers.'
)