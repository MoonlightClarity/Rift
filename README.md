# RIFT

Rift is a lightweight asynchronous web crawler for checking large lists of URLs and generating page metadata.

It uses Google DNS to resolve domains, makes HTTP/HTTPS requests, and records successfully reachable pages that return a 2xx status code and contain a page title.

# RIFT FEATURES

* Asynchronous URL checking
* Google DNS resolution using 8.8.8.8 and 8.8.4.4
* IPv4 connectivity checking
* HTTP and HTTPS support
* No redirect following
* SSL certificate verification disabled
* Page title extraction
* Concurrent processing
* Live progress and diagnostic reporting
* Windows GUI
* Separate DNS zone-file cleaner

# RIFT

Rift reads URLs from a user-selected input file, checks each URL, and writes successful results to a user-selected output file.

The default input filename is today.txt, but any text file containing URLs can be selected through the GUI.

A successful result is written in the following format:

https://example.com    Example Domain

The URL and page title are separated by a tab character.

Only responses with HTTP status codes from 200 through 299 and a non-empty page title are written to the output file.

# INPUT

The input file should contain one URL per line.

Example:

https://example.com
https://www.example.org
http://example.net

The input and output paths can be selected through the Rift GUI.

# OUTPUT

Successful pages are written to the selected output file.

Connection and crawler diagnostics are written separately to the selected diagnostic location.

# CLEANER

Cleaner is a separate utility for processing DNS zone files.

It extracts valid hostnames, removes duplicates and DNS service/meta records, and produces normalized HTTPS URLs.

Example output:

https://example.com
https://www.example.com
https://mail.example.com

Cleaner has its own Windows GUI with selectable input and output files.

# RUNNING FROM SOURCE

Python 3.13 or newer is recommended.

Install the required dependencies with:

pip install -r requirements.txt

Run Rift with:

python gui.py

Run Cleaner with:

python cleaner_gui.py

# WINDOWS EXECUTABLES

Prebuilt Windows executables can be distributed separately from the source code.

The distribution includes:

Rift
Cleaner

Both applications are standalone Windows builds and do not require Python to be installed.

# CONFIGURATION

Crawler settings can be adjusted through the Rift GUI.

Configurable settings include:

Input file
Output file
Diagnostic location
DNS servers
DNS timeout
Concurrency
Request timeout
Connection timeout
Socket timeouts

The default DNS servers are:

8.8.8.8
8.8.4.4

# PROJECT FILES

gui.py
scraper.py
cleaner.py
cleaner_gui.py
config.py
requirements.txt
README.txt
.gitignore

Generated files, build directories, runtime output, and diagnostic data are excluded from the source repository.

# LICENSE

This project is distributed under the MIT License.