# The Energy Bottleneck: Why Power Constraints Are the Real Limit on AI

Every conversation about AI scaling eventually becomes a conversation about energy. Training a frontier model requires thousands of GPUs running for months. Serving that model to millions of users requires data centres consuming megawatts of power around the clock. As AI workloads grow exponentially, the energy required to sustain them is colliding with the physical limits of electrical grids, the economics of power generation, and the politics of carbon emissions.

## The Numbers

The International Energy Agency estimates that global data centre electricity consumption will more than double between 2024 and 2028, rising from approximately 460 TWh to over 1,000 TWh. In the United States, data centres are projected to consume 12% of total grid electricity by 2028, up from roughly 4.4% in 2023. These figures include all data centres (cloud computing, streaming, enterprise IT), but AI workloads are the fastest-growing component.

A single large AI training cluster (the kind used to train frontier models) can draw 100-200 MW of power. For context, that's enough to power a small city. NVIDIA's next-generation GPU platforms are more energy-efficient per computation, but the total compute deployed is growing faster than efficiency improves. The net result is that AI's absolute energy consumption is accelerating.

This demand is already straining local grids. In Northern Virginia, the world's largest data centre market, new facilities face multi-year waits for grid connections. Utilities in Texas, Ohio, and Georgia are revising demand forecasts upward and scrambling to build new generation capacity. In Ireland, data centres now consume nearly a fifth of the national electricity supply, prompting the government to restrict new connections.

## The Nuclear Renaissance

The mismatch between AI's energy appetite and the capacity of existing grids has revived interest in nuclear power. Microsoft signed a deal to restart the Three Mile Island nuclear plant specifically to power its AI data centres. Amazon has invested in small modular reactors. Google and others have signed power purchase agreements with nuclear developers.

Nuclear offers something no other energy source can match for data centres: high-density, carbon-free, baseload power that runs 24/7 regardless of weather. Solar and wind are cheaper per kilowatt-hour in many markets, but they're intermittent. Data centres need continuous power, and battery storage at the required scale remains expensive. Natural gas is reliable but carbon-intensive, creating tension with corporate climate commitments.

Small modular reactors (SMRs) are the most discussed nuclear technology in the AI energy context. Companies like NuScale, Oklo, and Kairos Power are developing reactors that can be factory-built and deployed at or near data centre sites, potentially providing 50-300 MW of dedicated power. None are commercially operational yet (the first deployments are expected in the late 2020s), but the investment signals are strong.

The challenge is timeline. Nuclear projects take years to license and build, even with streamlined processes. AI's energy demand is growing now. This gap between demand and supply is one of the most significant constraints on the pace of AI scaling.

## Energy as Strategic Asset

The energy constraint transforms geography. AI infrastructure is migrating toward cheap, abundant power. Hydroelectric resources in Quebec and Scandinavia are attracting data centre investment. The Middle East is building AI compute centres powered by natural gas and, increasingly, solar. Iceland's geothermal energy has made it a surprisingly significant player in global compute.

This creates a new dimension of geopolitical competition. Countries with energy surpluses can attract AI infrastructure, which attracts talent, which attracts investment, which builds local AI ecosystems. Energy-poor countries face the opposite dynamic: they risk becoming dependent on AI services hosted elsewhere, much as they depend on imported oil today.

The parallel between energy and compute as strategic resources is becoming difficult to ignore. Intelligence per unit of energy is emerging as the fundamental efficiency metric of the AI era. The companies and countries that optimise this ratio (through better chips, more efficient algorithms, and access to cheap clean power) will have a structural advantage in everything AI enables.

## Efficiency vs. Demand

There is a counterargument: perhaps efficiency improvements will outpace demand growth. Algorithmic advances like mixture-of-experts, quantisation, and distillation have dramatically reduced the compute needed for inference (and therefore energy). New chip architectures achieve more operations per watt with each generation. Some researchers argue that the energy crisis is a temporary bottleneck that engineering will solve within a few years.

The history of computing offers a cautionary tale. Every previous efficiency improvement has been overwhelmed by increased usage, a phenomenon known as Jevons' paradox. When inference becomes ten times cheaper, usage increases by more than ten times because previously uneconomic applications become viable. Cheaper AI doesn't reduce total energy consumption. It expands the frontier of what AI is used for, which increases total energy consumption. The bottleneck moves but doesn't disappear.
