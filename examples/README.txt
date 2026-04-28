PythonOS examples

Run these from the kernel shell:

  run('/examples/ascii_graphics.py')
  sh('/examples/ascii_graphics.py')
  run('/examples/tone.py')
  run('/examples/mini_vi.py')
  cat /examples/README.txt

File transfer:

  Inbound to PythonOS:
    ftp get /tmp/inbox.txt
    host: nc localhost 17000 < local-file.txt

  Outbound from PythonOS:
    host: nc -l 7001 > from-pythonos.txt
    ftp put /tmp/inbox.txt

The recv_file.py and send_file.py examples show the lower-level TCP APIs
used by the ftp command.

The examples are frozen as Python modules and their source is seeded into
TmpFS so they remain readable at /examples.
