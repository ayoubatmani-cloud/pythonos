PythonOS examples

Run these from the kernel shell:

  run('/examples/hello_kernel.py')
  sh('/examples/hello_kernel.py visitor')
  run('/examples/vfs_demo.py')
  sh('/examples/vfs_demo.py /tmp/custom-vfs-demo.txt')
  run('/examples/async_tasks.py')
  sh('/examples/primes.py 100')
  run('/examples/tone.py')
  cat /examples/README.txt

What they show:

  hello_kernel.py  Inspect cwd, root TmpFS entries, and scheduler tasks
  vfs_demo.py      Write and read a TmpFS file through the VFS API
  async_tasks.py   Pass values between cooperative asyncio tasks
  primes.py        Run a small pure-Python computation
  tone.py          Build a tiny PCM tone buffer for HDA when available

File transfer:

  Inbound to PythonOS:
    ftp get /tmp/inbox.txt
    host: nc localhost 17000 < local-file.txt

  Outbound from PythonOS:
    host: nc -l 7001 > from-pythonos.txt
    ftp put /tmp/inbox.txt

Lower-level TCP examples:

  Inbound to PythonOS:
    sh('/examples/recv_file.py 7000 /tmp/inbox.bin')
    host: nc localhost 17000 < local-file.txt

  Outbound from PythonOS:
    host: nc -l 7001 > pythonos-example.txt
    sh('/examples/send_file.py 10.0.2.2 7001 /examples/README.txt')

The examples are frozen as Python modules and their source is seeded into
TmpFS so they remain readable at /examples.
