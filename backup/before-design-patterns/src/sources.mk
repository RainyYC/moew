# Canonical translation unit order. Shared by the multi-TU build and exporter.
SOLVER_SOURCES := \
	src/solver.cpp \
	src/app/solver.cpp \
	src/io/numeric.cpp \
	src/io/input.cpp \
	src/io/options.cpp \
	src/io/output.cpp \
	src/placement/expert_mapping.cpp \
	src/placement/grouped_placement.cpp \
	src/scheduling/event_scheduler.cpp \
	src/scheduling/list_scheduler.cpp \
	src/search/candidate_search.cpp \
	src/search/layout_search.cpp \
	src/search/window_search.cpp \
	src/search/initial_search.cpp \
	src/search/window_borrow.cpp \
	src/search/boost_search.cpp \
	src/search/placement_search.cpp \
	src/search/list_search.cpp \
	src/search/wave_search.cpp \
	src/search/local_engine_polish.cpp \
	src/search/polish_driver.cpp
