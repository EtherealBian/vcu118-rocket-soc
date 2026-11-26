# OOC structural experiment. No timing exceptions, no bitstream, no board access.
if {$argc != 3} {error {usage: <unmodified|marked> <leaf.sv> <new-directory>}}
lassign $argv mode file out; set file [file normalize $file]; set out [file normalize $out]
if {$mode ni {unmodified marked} || ![file isfile $file] || [file exists $out]} {error {invalid inputs}}
file mkdir $out; cd $out; set_param general.maxThreads 2
read_verilog -sv $file; synth_design -mode out_of_context -part xcvu9p-flga2104-2L-e -top NonSyncResetSynchronizerPrimitiveShiftReg_d3
set ffs [get_cells -quiet -hier -filter {REF_NAME =~ FD*}]; set srl [get_cells -quiet -hier -filter {REF_NAME =~ SRL*}]
puts "IRQ_SYNC_OOC mode=$mode flipflops=[llength $ffs] shift_luts=[llength $srl]"; report_utilization -file utilization.rpt
if {$mode eq "marked"} {
  if {[llength $srl] || [llength $ffs]!=3} {error {expected three real flip-flops}}
  foreach i {2 1 0} {set c [get_cells sync_${i}_reg]; if {[get_property ASYNC_REG $c] ni {1 TRUE true}} {error "missing ASYNC_REG $c"}}
  foreach {src dst} {2 1 1 0} {set ends [all_fanout -flat -endpoints_only -from [get_pins sync_${src}_reg/Q]]; if {[llength $ends]!=1 || $ends ne "sync_${dst}_reg/D"} {error "broken chain: $ends"}}
  set ends [all_fanout -flat -endpoints_only -from [get_ports io_d]]; if {[llength $ends]!=1 || $ends ne "sync_2_reg/D"} {error "unexpected input loads $ends"}
  set ends [all_fanout -flat -endpoints_only -from [get_pins sync_0_reg/Q]]; if {[llength $ends]!=1 || $ends ne "io_q"} {error "unexpected output loads $ends"}
}; write_checkpoint result.dcp; puts IRQ_SYNC_OOC_INSPECTED_NO_SOC_SIGNOFF
