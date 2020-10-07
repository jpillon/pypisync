# pypisync

The goal of **PypiSync** is to keep consistency when syncing packages from pypi.org. 
This means that when mirroring the latest packages only or just a list of packages, it tries to ensure that these will be installable without the need to resolve the dependencies manually.  

It uses: 
  * the **XMLRPC** API to get the packages list (when using the "packages_re" matching).
    * This is much faster than parsing the simple index
  * the **JSON** API to get the packages files/urls 

# Configuration

Here is some documentation for the configuration:  

```json5
{
    "endpoint": null,                        // The pypi endpoint. Defaults to https://pypi.org/
                                             // The endpoint must implement:
                                             //   the Pypi XMLRPC protocol on endpoint/pypi
                                             //   the Pypi JSON "protocol":
                                             //     endpoint/package_name/json
                                             //     endpoint/package_name/version/json)
    "destination_folder": "../data",         // Where to put the downloaded data
    "arch_exclude": null,                    // A list that will be used to exclude some files based on the 
                                             // remaining of its name after removing the name and version
                                             //   Example:
                                             //     for a file named project-1.2.3-cp27-cp27m-win_amd64.whl
                                             //     The elements of arch_exclude will be searched in:
                                             //       "-cp27-cp27m-win_amd64.whl"  
    "environment": {                         // Environment defined when gathering a package dependencies.
                                             //   See documentation on "PEP 508" for more information 
                                             //   Each parameter is either null or a list of strings. 
                                             //   If a parameter is null, all values are allowed.
        "os_name": null,
        "sys_platform": null,
        "platform_machine": null,
        "platform_python_implementation": null,
        "platform_release": null,
        "platform_system": null,
        "platform_version": null,
        "python_version": null,
        "python_full_version": null,
        "implementation_name": null,
        "implementation_version": null,
        "extra": null                        // This might be the most useful when syncing a small subset.
                                             //   For example, setting null here for awscli will result 
                                             //   in downloading more than 3GB of dependencies. 
                                             //   Just put an empty list to download the direct dependencies only.  
    },
    "packages": {                            // Configuration of what to download.
                                             //   The key is the name of the package
                                             //   The value is a list of versions. A version can be: 
                                             //      A strict version: "1.2"
                                             //      A version specifier: 
                                             //        All matching versions will be downloaded
                                             //        "<3"
                                             //        "<3,>2"
                                             //        ">=1.2.3"
                                             //      A "latest" version specifier.
                                             //        "latest" is equivalent to "1 latest"
                                             //        "5 latest": The latest versions
                                             //        "2 latest<3": The two last versions before 3.0.0
      "django": ["latest", "latest<3"]       //   A useful example for Django:
                                             //       Permits to sync the latest Django2 alongside
                                             //       the real latest version       
                                                     
    },
    "packages_re": {                         // The syntax here is equivalent to the "packages", 
                                             // but the package name is a regular expression
        ".*": ["latest"]                     // Download all the packages in their last version
    }
}
```