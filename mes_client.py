import sys
from mes_api import MESClient

mes = MESClient()

if sys.argv[1] == "query":
    mes.query_api(sys.argv[2]) # runcard
elif sys.argv[1] == "enter":
    mes.enter_api(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]) # runcard, sn, process_name, employee_no
elif sys.argv[1] == "leave":
    mes.leave_api(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]) # runcard, sn, operator, wo, process_name
