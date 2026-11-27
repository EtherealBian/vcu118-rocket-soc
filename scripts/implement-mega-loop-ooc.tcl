# One pair of local comparisons, not SoC implementation or a board clock.
if {$argc != 2} {error {usage: prepared-pair fresh-output}}
set dir [file normalize [lindex $argv 0]]; set out [file normalize [lindex $argv 1]]
if {[file exists $out] || ![string match {2024.2*} [version -short]]} {error {needs fresh output and Vivado 2024.2}}
file mkdir $out; set_param general.maxThreads 2
proc putpath {f label p} {
    puts $f [join [list $label [get_property SLACK $p] [get_property DATAPATH_DELAY $p] [get_property LOGIC_LEVELS $p] [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p]] "\t"]
}
foreach name {stock candidate} {
    set work [file join $out $name]; file mkdir $work; cd $work
    create_project -in_memory -part xcvu9p-flga2104-2L-e
    foreach m {LoopBranchPredictorColumn LoopBranchPredictorBank} {read_verilog -sv [file join $dir $name $m.sv]}
    read_verilog [file join $dir boundary.v]; read_xdc [file join $dir loop.xdc]
    synth_design -mode out_of_context -top loop_boundary -part xcvu9p-flga2104-2L-e
    opt_design; place_design; route_design
    report_route_status -file route.rpt; report_timing_summary -report_unconstrained -file timing.rpt; report_utilization -file util.rpt
    set clk [get_clocks cpu]; if {[llength $clk]!=1 || abs([get_property PERIOD $clk]-5.714)>0.0001} {error {missing CPU clock}}
    set regs [all_registers -clock $clk]
    set f [open paths.tsv {WRONLY CREAT EXCL}]; puts $f "group\tslack_ns\tdata_ns\tlevels\tfrom\tto"
    foreach kind {max min} {
        set paths [get_timing_paths -from $regs -to $regs -delay_type $kind -max_paths 10 -nworst 1]
        if {[llength $paths]!=10} {error {missing register endpoints}}
        report_timing -of_objects $paths -input_pins -file registers-$kind.rpt
        foreach p $paths {putpath $f all-$kind $p}
    }
    for {set lane 0} {$lane<4} {incr lane} {
        # b_io_resp_f3_<lane>_taken is one specific output-capture FDRE.
        set ff [get_cells -quiet b_io_resp_f3_${lane}_taken_reg]
        if {[llength $ff]!=1 || ![string match {FD*} [get_property REF_NAME $ff]]} {error "no unique capture register on lane $lane"}
        set p [get_timing_paths -from $regs -to [get_pins $ff/D] -delay_type max -max_paths 1]
        if {[llength $p]!=1} {error {missing taken capture}}
        report_timing -of_objects $p -input_pins -file taken-$lane.rpt; putpath $f taken-$lane $p
    }
    if {$name eq "candidate"} {
        set regs1 [get_cells -hier -filter {NAME =~ *vcu_f3_repair_bypass_reg* && REF_NAME =~ FD*}]
        if {[llength $regs1]!=4} {error {could not identify all four new enable flops}}
        foreach ff $regs1 {
            set p [get_timing_paths -from $regs -to [get_pins $ff/D] -delay_type max -max_paths 1]; if {[llength $p]!=1} {error {missing early-stage path}}; putpath $f early-enable $p
        }
    }
    close $f; close_project; puts "LOOP_BANK_OOC_CASE_COMPLETE $name"
}
puts LOOP_BANK_OOC_PAIR_COMPLETE_NOT_SOC_TIMING
