\# PyPSA-AR Data Dictionary (Aligned with Defined Scope)



This document defines the target PyPSA structure for v0.1:



500 kV backbone + selected 220/132 kV nodes.



The dictionary defines minimum required fields for each component.



---



\## 1. Buses



Represents electrical nodes.



Scope:



\- All 500 kV nodes

\- Selected 220/132 kV nodes (strategic only)



Required Fields:



\- name

\- x (longitude)

\- y (latitude)

\- v\_nom (kV)

\- carrier = electricity



Optional:



\- region

\- country

\- substation\_name



---



\## 2. Lines



Represents transmission lines.



Scope:



\- All 500 kV lines

\- Selected 220/132 kV segments (only where structurally relevant)



Required Fields:



\- name

\- bus0

\- bus1

\- r (resistance)

\- x (reactance)

\- s\_nom (thermal limit, MVA)

\- length (km)

\- carrier = AC





---



\## 3. Transformers



Used only where voltage coupling is necessary.



Required Fields:



\- name

\- bus0

\- bus1

\- r

\- x

\- s\_nom





---



\## 4. Loads



Represents electricity demand.



Required Fields:



\- name

\- bus

\- p\_set (reference to hourly time series)



Time Series:



\- 8760 hours (2024 base year)



---



\## 5. Generators



Represents existing power plants.



Required Fields:



\- name

\- bus

\- p\_nom (MW)

\- carrier (gas, hydro, nuclear, wind, solar, diesel)

\- marginal\_cost (USD/MWh)



Thermal Units:



\- efficiency

\- fuel type



Renewables:



\- availability time series



Optional:



\- ramp limits

\- minimum generation constraints

\- emission intensity



---



\## 6. Carriers



Defines energy types.



Examples:



\- electricity

\- gas

\- nuclear

\- hydro

\- wind

\- solar

\- diesel



Attributes:



\- co2\_emissions (tCO2/MWh)

\- color (for visualization)



---



\## 7. Time Series Data



Hourly data (8760h):



\- Demand

\- Wind availability

\- Solar availability

\- Hydro availability (if modeled dynamically)



Time index:



\- Hourly resolution

\- Single calibration year (2024)



---



\## Modeling Philosophy



\- Start simple.

\- Represent backbone accurately.

\- Add lower voltage detail only where necessary.

\- Calibrate before expanding complexity.



---



This dictionary defines the structural target for ETL development.



