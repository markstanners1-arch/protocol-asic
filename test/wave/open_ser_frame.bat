@echo off
rem Open the serialiser recording in GTKWave with the signals laid out (double-click this file).
rem If ser_frame.vcd is missing, make it first: bash test/wave/run_ser_frame.sh
cd /d "%~dp0"
set PATH=D:\Tools\oss-cad-suite\bin;D:\Tools\oss-cad-suite\lib;%PATH%
start "" gtkwave.exe ser_frame.vcd ser_frame.gtkw
