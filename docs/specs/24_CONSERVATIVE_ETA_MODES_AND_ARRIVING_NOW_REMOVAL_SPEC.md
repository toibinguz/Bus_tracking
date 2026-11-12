# SPEC-24: ETA bao thu, che do Passenger/Debug va bo `ARRIVING_NOW`

> Thiết kế giữ để tra hợp đồng; trạng thái/số liệu/giao diện gốc cần đối chiếu code/test. Xem [chỉ mục](README.md). Không tự thực thi phân công agent hoặc lệnh dọn file lịch sử.


**Trang thai:** APPROVED PRODUCT DECISION — chua trien khai  
**Phạm vi:** Module 3.4/3.5, giu nguyen model ML, baseline va cac module frozen theo SPEC-19.

## 1. Quyết định đã chốt

1. ETA cho hành khách la ETA bao thu: uu tien giam rui ro den muon, khong tao ETA khi BusMap live rong.
2. Demo co hai che do trinh bay: **Passenger** (toi gian) va **Debug** (chan doan day du). Day la che do UI, khong thay doi du lieu hay ket qua suy luan API.
3. Xoa hoan toan trang thai/nhanh `ARRIVING_NOW`. Heartbeat hien tai khong du phan giai de khang dinh xe dang cap ben. Truong `status` chi ton tai de bieu dat `IN_TRANSIT | ARRIVING_NOW` nen cung phai bi xoa khoi DTO, API va UI.

## 2. Mo hinh ETA: giu cong thuc da co, khong them hang so moi

Voi moi xe da duoc loc la **approaching** boi logic hinh hoc hien co, dat:

- `T50` = `ml_p50` khi `ModelRuntime.available` va `predict_p50` thanh cong; neu khong, `baseline_p50`.
- `sigma` = do lech chuan tich luy cua cac segment baseline.
- `kappa(d)` = ham suy giam can ben hien co trong `eta_policy`.
- `B = clamp(kappa(d) * (alpha*sigma + beta*heartbeat + gamma*T50), 0, MAX_SAFE_BUFFER_CEILING_SEC)`, voi `alpha`, `beta`, `heartbeat`, `gamma` chi lay tu `config.system_config` hien co.
- `Tc = T50 + B` la ETA bao thu; `M = ceil(Tc / 60)` la so phut hien thi.

Khong duoc cong them mot so phut co dinh, doi model, doi baseline matrix, hay them hysteresis theo thoi gian trong milestone nay. Lam tron len theo phut la co che on dinh duy nhat duoc phep; `T50`, `B`, `Tc` van phai quan sat duoc o Debug.

## 3. He qua cua viec bo `ARRIVING_NOW`

`compute_station_eta` phai bo nhanh early-return dua tren `STATION_ARRIVING_ENTRY_M`/`STATION_ARRIVING_EXIT_M`. Mot xe approaching, ke ca rat gan tram, di qua cung mot duong tinh o muc 2; khong co `display_eta_minutes=0`, `eta_seconds=0`, hay text “Dang cap ben” do nguong khoang cach.

- Xoa `status` khoi `ApproachingBusDTO`, tat ca construction sites, OpenAPI schema, JavaScript va tai lieu API.
- Xoa cac constant `STATION_ARRIVING_ENTRY_M` va `STATION_ARRIVING_EXIT_M` neu sau thay doi chung khong con consumer nao. `STATION_BUFFER_ATTEN_*` phai giu nguyen vi van dinh nghia `kappa(d)`.
- `display_text` chi co `~1 phut` khi `M=1` va `M phut` khi `M>=2`. Neu nhu mot input hop le tao `M=0`, text phai la `0 phut`, khong dung mot nhan trang thai vat ly.
- Loc xe da qua tram van la trach nhiem cua luong approaching hien co; khong duoc dua xe da qua tram vao de thay the `ARRIVING_NOW`.

## 4. Contract Passenger/Debug

Khong tao them API mode hay thay doi cong thuc theo che do. `/api/station-eta` giu mot response thuc duy nhat; UI local co mot toggle ro rang va mac dinh **Debug** trong demo nay de phuc vu kiem tra ca nhan.

| Che do | Hien thi bat buoc | An |
| --- | --- | --- |
| Passenger | xe gan nhat, `display_text` theo `M`, bien so, so tram con lai, thong diep empty state | P10/P50/P90, `B`, `Tc`, nguon model, ping age, toc do, traffic va cac ly do loc |
| Debug | Toan bo Passenger, them `prediction_source`, P10/P50/P90, `T50`, `B`, `Tc`, `M`, ping time/age, speed, distance, stops, traffic/delay va ly do empty state | credential, token, raw provider payload |

`prediction_source` phai phan biet it nhat `ml_calibrated` va `baseline_fallback`; no la fact cua runtime, khong duoc suy doan tu gia tri ETA. Neu contract hien tai chua mang du lieu can thiet de UI hien thi bang Debug, bo sung cac truong readonly co ten/ don vi ro rang, khong render raw provider data.

## 5. Compatibility va migration

- Day la breaking API change co chu y: client con doc `status` phai cap nhat trong cung release; khong giu alias `ARRIVING_NOW` hay truong zombie.
- UI Passenger/Debug phai dung mot response; doi toggle khong duoc tao forecast moi hay thay doi `M`.
- Empty states phai phan biet: upstream khong co xe, khong co xe approaching, geometry chua san sang, va input khong hop le. Khong hien “gian cach ~10-15 phut” neu khong co du lieu de tinh.

## 6. Ke hoach nghiem thu

1. **Leaf coder:** sua DTO/policy/serving/UI dung pham vi tren; xoa import/constant mo coi do thay doi tao ra.
2. **White-box audit:** doi chieu cong thuc `T50/B/Tc/M`, xac nhan khong them hang so; xac nhan khong con nhanh, enum, OpenAPI hay UI reference `ARRIVING_NOW`/`status`.
3. **Blind black-box test:** doi chieu `M = ceil(Tc/60)`, Passenger an diagnostic, Debug hien diagnostic nhat quan, `prediction_source` ML/fallback observable, empty states trung thuc, va payload khong co `status` hay `ARRIVING_NOW`.

## 7. Acceptance criteria

- Khong con match `ARRIVING_NOW` trong source, test, docs active hay OpenAPI sau migration.
- Moi ETA tra ve tu xe approaching co `Tc >= T50`, `B >= 0`, `M = ceil(Tc/60)`; khong co cong them hang so tu UI.
- Model ML van duoc goi khi artifact available; fallback baseline van hoat dong khi model unavailable.
- Passenger va Debug chi khac nhau o trinh bay; cung mot response co cung `M`.
- Khong thay doi Module 1, 2, 3.1–3.3, data/model artifact, hoac frontend redesign deferred.
