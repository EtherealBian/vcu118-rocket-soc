# One case per Vivado process: compare only the registered local cone on the VCU118 part.
if {$argc ni {3 4}} {error {usage: prepared-input fresh-output stock|class_local|split_rsp ?opt-only?}}
set opt_only [expr {$argc==4}]; if {$opt_only && [lindex $argv 3] ne {opt-only}} {error {unknown stage}}
lassign $argv in out name; set in [file normalize $in]; set out [file normalize $out]
if {$name ni {stock class_local split_rsp} || [file exists $out] || ![file isfile [file join $in bound.json]] || ![string match {2024.2*} [version -short]]} {error {need certified inputs, fresh output and Vivado 2024.2}}
set_param general.maxThreads 1; set_param synth.maxThreads 1
file mkdir $out; cd $out
create_project -in_memory -part xcvu9p-flga2104-2L-e
read_verilog [file join $in $name.v]; read_verilog [file join $in boundary.v]; read_xdc [file join $in clock.xdc]
synth_design -mode out_of_context -top boundary -part xcvu9p-flga2104-2L-e
opt_design
if {$opt_only} {
    write_checkpoint local-opt.dcp
} else {
    place_design; route_design
    # Keep the route even if a probe name is missing after synthesis/placement.
    write_checkpoint local-routed.dcp
    report_route_status -file route.rpt
}
report_timing_summary -report_unconstrained -file timing.rpt; report_utilization -file util.rpt
set clk [get_clocks cpu]; if {[llength $clk]!=1 || abs([get_property PERIOD $clk]-5.714)>0.0001} {error {wrong clock}}
set f [open paths.tsv {WRONLY CREAT EXCL}]; puts $f "group\toutput\tslack_ns\tdata_ns\tlevels\tfrom\tto"
proc sample {f name idx src d} {
    if {![llength $src]} {error "no sources for $name"}
    set p [get_timing_paths -quiet -from $src -to $d -delay_type max -max_paths 1]; if {[llength $p]!=1} {error "missing path $name $idx"}
    report_timing -of_objects $p -input_pins -file [format {path-%s-%d.rpt} $name $idx]
    puts $f [join [list $name $idx [get_property SLACK $p] [get_property DATAPATH_DELAY $p] [get_property LOGIC_LEVELS $p] [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p]] "\t"]
}
set all [all_registers -clock $clk]
for {set i 0} {$i<3} {incr i} {
    set capture [get_cells -quiet [list [format {result_reg[%d]} $i]]]; if {[llength $capture]!=1} {error "bad capture $i"}; set d [get_pins $capture/D]
    sample $f all $i $all $d
    if {$i==2} {
        foreach {label patt} {branch q_dc_io_lsu_brupdate_b1_mispredict_mask_reg* address1 q_dc_s2_req_1_addr_reg* state q_m?_state_reg* rpq q_q?_*_reg*} {
            set src [get_cells -hierarchical -quiet -filter "IS_SEQUENTIAL == 1 && NAME =~ $patt"]
            sample $f $label $i $src $d
        }
    }
}
close $f
if {$opt_only} {puts "MSHR_OOC_OPT_ONLY_NOT_ROUTED $name"} else {puts "MSHR_REGISTERED_OOC_COLLECTED $name"}
