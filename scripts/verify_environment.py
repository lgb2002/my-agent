"""Check installed runtime; never prints .env values or calls network."""
import importlib.metadata as md
import sys


if __name__ == '__main__':
    print('Python:',sys.version.split()[0], '(target 3.12)')
    names=['streamlit','python-dotenv','langchain','langchain-openai','requests']
    missing=[]
    for name in names:
        try:
            print('{}: {}'.format(name,md.version(name)))
        except md.PackageNotFoundError:
            print('{}: MISSING'.format(name))
            missing.append(name)
    if sys.version_info[:2] != (3,12):
        print('NOTE: Current interpreter differs from target Python 3.12')
    if missing:
        print('Install missing dependencies with: python -m pip install python-dotenv langchain langchain-openai')
        sys.exit(1)
