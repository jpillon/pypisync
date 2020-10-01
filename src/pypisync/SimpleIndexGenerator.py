import os
import pypi_simple


class SimpleIndexGenerator:
    """
    Simple index generator
    """

    package_begin = """<!DOCTYPE html>
<html>
  <head>
    <title>Links for {package_name}</title>
  </head>
  <body>
    <h1>Links for {package_name}</h1>
"""

    package_link = '    <a href="{link}#sha256={hash}">{basename}</a><br/>\n'

    package_end = """  </body>
</html>
"""

    def __init__(self, simple_root):
        self._simple_root = simple_root

    def generate(self, packages):
        """
        Generates an index for each package
        :param packages: the list of packages
        """

        # Begin with grouping packages
        grouped = {}
        for package in packages:
            package_name = pypi_simple.normalize(package.name)
            if package_name not in grouped:
                grouped[package_name] = {
                    "package_root": os.path.join(self._simple_root, package_name),
                    "links": [],
                    "basenames": [],
                    "file_hashes": []
                }
            link = os.path.relpath(package.local_file, grouped[package_name]["package_root"])
            grouped[package_name]["links"].append(link)
            grouped[package_name]["basenames"].append(os.path.basename(package.local_file))
            grouped[package_name]["file_hashes"].append(os.path.basename(package.file_hash))

        for package_name in grouped:
            os.makedirs(grouped[package_name]["package_root"], exist_ok=True)
            with open(os.path.join(grouped[package_name]["package_root"], "index.html"), "wt") as index_html:
                index_html.write(self.package_begin.format(package_name=package_name))
                for link, basename, file_hash in zip(
                        grouped[package_name]["links"],
                        grouped[package_name]["basenames"],
                        grouped[package_name]["file_hashes"]
                ):
                    index_html.write(
                        self.package_link.format(
                            link=link,
                            basename=basename,
                            hash=file_hash
                        )
                    )
                index_html.write(self.package_end)
