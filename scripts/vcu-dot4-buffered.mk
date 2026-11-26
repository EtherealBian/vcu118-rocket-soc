# Isolated assembly: leave both the stock source set and the original buffered kit unchanged.
$(GENERATOR_CLASSPATH): $(VCU_BUFFER_CONFIG) $(VCU_COMBINED_CONFIG) $(VCU_BUFFER_PATCHED) $(VCU_COMBINED_MK)
define run_sbt_assembly
	cd $(base_dir) && $(SBT) ';project $(1); $(if $(filter $(GENERATOR_CLASSPATH),$(2)),set LocalProject("rocketchip") / Compile / unmanagedSources ~= { xs => xs.map(f => if (f.getCanonicalPath == "$(VCU_BUFFER_ORIGINAL)") file("$(VCU_BUFFER_PATCHED)") else f) }; set Compile / unmanagedSources ++= Seq(file("$(VCU_BUFFER_CONFIG)")$(comma) file("$(VCU_COMBINED_CONFIG)"));) set assembly / assemblyOutputPath := file("$(2)"); assembly' && touch $(2)
endef
comma := ,
