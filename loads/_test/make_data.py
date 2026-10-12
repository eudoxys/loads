import pandas as pd
import numpy as np

pd.options.display.width = None

ami = pd.read_csv("~/Downloads/sce_ami.csv.gz")

def anonymize(df,column):
	lookup = {y:x for x,y in enumerate(df[column].unique())}
	df[column] = np.array(lookup[x] for x in df[column])
	return df

anonymize(ami,"circuit_name")
anonymize(ami,"customer_id")
ami.drop(["record_id","energy_unit"],axis=1,inplace=True)
ami.rename({
	"circuit_name":"circuit_id",
	"customer_id":"meter_id",
	"record_date":"date",
	"hour_id":"hour",
	"utc_offset":"tz_offset",
	"energy_value":"kwh_delta",
	}, axis=1,inplace=True)
ami.sort_values(["date","hour","circuit_id","meter_id"],inplace=True)
ami.to_csv("ami.csv.gz",index=False,header=True,compression="gzip")