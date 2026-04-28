PythonOS examples

Run these from the kernel shell:

  run('/examples/ascii_graphics.py')
  run('/examples/tone.py')
  run('/examples/mini_vi.py')

File transfer:

  Inbound to PythonOS:
    run('/examples/recv_file.py')
    host: printf hello | nc localhost 7000

  Outbound from PythonOS:
    host: nc -l 7001 > pythonos-example.txt
    run('/examples/send_file.py')

The examples are frozen as Python modules and their source is seeded into
TmpFS so they remain readable at /examples.
