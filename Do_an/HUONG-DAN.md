# Mẫu báo cáo Đồ án Trí tuệ nhân tạo (AIP202)

Khoa Công nghệ Thông tin, Trường Đại học Kiến trúc Đà Nẵng.

Gói này là khung LaTeX để em viết báo cáo đồ án học phần. Trang bìa, mục lục,
các danh mục, header, bảng biểu, hộp trình bày và danh mục tài liệu tham khảo
đã dựng sẵn theo nhận diện của trường. Việc của em là điền nội dung.

## 1. Cách nhanh nhất: dùng Overleaf

1. Vào [overleaf.com](https://www.overleaf.com), đăng ký tài khoản miễn phí.
2. Chọn **New Project** rồi **Upload Project**, kéo cả file zip này vào.
3. Mở **Menu** ở góc trên bên trái, mục **Compiler** chọn **XeLaTeX**, và mục
   **Main document** chọn `do-an.tex`.
4. Mở file `do-an.tex`, bấm **Recompile**.

Gói này có sẵn file `latexmkrc` ép dùng XeLaTeX, nên kể cả khi em quên đổi
Compiler thì Overleaf vẫn build đúng. Nhưng cứ đặt cho chắc.

## 2. Nếu build trên máy mình

Cần TeX Live 2023 trở lên hoặc MiKTeX, cùng phông Noto Sans. Mở terminal tại
thư mục này rồi chạy:

```
latexmk -xelatex do-an.tex
```

Lệnh này tự chạy đủ số lượt và tự gọi BibTeX để dựng danh mục tài liệu tham
khảo. Dọn file trung gian bằng `latexmk -c`. Máy không có Noto Sans thì báo
cáo vẫn build được, chỉ khác kiểu chữ.

## 3. Em sửa những file nào

| File | Sửa hay không | Nội dung |
|---|---|---|
| `do-an.tex` | **Sửa đầu tiên** | Khối thông tin ở đầu file: tên đề tài, họ tên, MSSV, lớp, GVHD |
| `chuong/*.tex` | **Sửa nhiều nhất** | Từng chương của báo cáo |
| `refs.bib` | Sửa khi thêm tài liệu | Danh mục tài liệu tham khảo |
| `figs/` | Bỏ ảnh vào đây | Ảnh chụp màn hình, sơ đồ, biểu đồ |
| `code/` | Bỏ mã nguồn vào đây | File mã để nạp vào báo cáo |
| `styles/dau.sty` | **Không sửa** | Định dạng chung |
| `styles/settings.tex` | **Không sửa** | Lớp tài liệu và thiết lập chung |

Cấu trúc chương:

```
chuong/00-loi-cam-doan.tex        Lời cam đoan
chuong/00-loi-cam-on.tex          Lời cảm ơn
chuong/00-tom-tat.tex             Tóm tắt, viết sau cùng
chuong/01-mo-dau.tex              Lý do, mục tiêu, phạm vi, bố cục
chuong/02-co-so-ly-thuyet.tex     Lý thuyết nền, công cụ, công trình liên quan
chuong/03-phan-tich-thiet-ke.tex  Phân tích, kiến trúc, dữ liệu, mô hình
chuong/04-cai-dat.tex             Môi trường, mã nguồn, demo, kiểm thử
chuong/05-ket-qua-danh-gia.tex    Kết quả, độ đo, bàn luận, hạn chế
chuong/06-ket-luan.tex            Kết luận, bài học, hướng phát triển
chuong/07-phu-luc.tex             Hướng dẫn chạy, bảng tự kiểm, trang nhận xét
chuong/99-quy-cach-trinh-bay.tex  Sổ tra cứu, XOÁ trước khi nộp
```

## 4. Chương 99 là sổ tra cứu, không phải một chương của báo cáo

File `chuong/99-quy-cach-trinh-bay.tex` gom sẵn mẫu cho mọi thứ em cần dùng:
chèn hình, vẽ sơ đồ bằng TikZ, làm bảng, viết công thức, chèn mã nguồn, viết
giải thuật bằng mã giả, trích dẫn, chú thích cuối trang và các hộp nhấn mạnh.
Em mở ra copy đoạn nào cần rồi sửa.

Trước khi nộp bản chính thức, xoá dòng `\input{chuong/99-quy-cach-trinh-bay}`
trong file `do-an.tex`.

## 5. Hai loại khối em phải xử lý

**Hộp gợi ý** nền xám, bắt đầu bằng chữ *Gợi ý*. Đây là lời dặn của giảng viên
về việc cần viết gì trong mục đó. Đọc xong thì xoá cả khối:

```latex
\begin{chuy}
\goiy{...}
\end{chuy}
```

**Khối nội dung mẫu** có vạch xám dọc bên trái và dòng chữ nhỏ *NỘI DUNG MẪU*.
Đây là văn mẫu minh hoạ định dạng, không phải bài của em. Thay bằng nội dung
thật rồi xoá cả cặp `\begin{mau}` và `\end{mau}`.

Nộp bài mà còn sót chữ *NỘI DUNG MẪU* trong PDF là lỗi bị trừ điểm nhiều nhất
khi dùng mẫu có sẵn. Trước khi nộp hãy tìm chuỗi đó trong bản PDF.

## 6. Các lệnh trình bày có sẵn

| Lệnh hoặc môi trường | Dùng để |
|---|---|
| `\en{sentiment analysis}` | Thuật ngữ tiếng Anh chèn nội tuyến |
| `\code{min_df}` | Tên biến, tên lệnh, tên file |
| `\term{cơ sở tri thức}` | Nhấn mạnh thuật ngữ tiếng Việt lần đầu |
| `\cite{Krizhevsky2012}` | Trích dẫn tài liệu khai trong `refs.bib` |
| `\begin{dinhnghia}[Nhãn]` | Hộp định nghĩa khái niệm |
| `\begin{ghinho}` | Hộp ghi nhớ, ý chốt |
| `\begin{luuy}` | Hộp lưu ý, cảnh báo lỗi hay gặp |
| `\begin{vidu}[Tên]` | Hộp ví dụ, tự đánh số theo chương |
| `\begin{muctieu}` | Hộp mục tiêu, đặt ở đầu mỗi chương |
| `\begin{tukiem}` | Danh sách có ô vuông để tự đánh dấu |
| `\begin{lstlisting}[language=Python]` | Khối mã nguồn có tô màu |
| `\lstinputlisting{code/ten-file.py}` | Nạp mã nguồn từ file |
| `\begin{algorithm}` | Trình bày giải thuật bằng mã giả |

Quy ước của khoa: comment trong code viết bằng tiếng Anh, còn văn xuôi của báo
cáo viết bằng tiếng Việt. Không đặt tiếng Việt bên trong khối mã nguồn.

## 7. Đổi kiểu bìa

Mặc định là bìa trang trọng có khung kép, đúng kiểu quyển đồ án nộp khoa. Nếu
em muốn bìa hiện đại theo bộ giáo trình của khoa, mở `do-an.tex` và đổi dòng
`\coverpage` thành `\coverpagehiendai`.

## 8. Lỗi hay gặp

| Triệu chứng | Nguyên nhân và cách sửa |
|---|---|
| Overleaf báo `no legal \end found` và nhắc tới `settings.tex` | Overleaf đang lấy nhầm file chính. Vào Menu, mục **Main document**, chọn `do-an.tex` |
| Tiếng Việt mất dấu hoặc ra ô vuông | Đang build bằng pdfLaTeX. Chuyển sang XeLaTeX |
| `File 'styles/dau.sty' not found` | Giải nén thiếu thư mục, hãy giải nén lại đủ cả cây thư mục |
| Trích dẫn ra dấu `[?]` | Chưa chạy BibTeX. Dùng `latexmk -xelatex` thay vì gọi `xelatex` tay |
| Tham chiếu ra dấu `??` | Build lại lần nữa, LaTeX cần nhiều lượt |
| Hình không hiện | Sai tên file hoặc quên bỏ ảnh vào `figs/` |
| Bảng hoặc sơ đồ tràn lề | Bọc trong `\resizebox{\textwidth}{!}{...}` như ví dụ ở chương 99 |
| `Undefined control sequence \tendetai` | Xoá nhầm một dòng khai báo ở đầu `do-an.tex` |

## 9. Trước khi nộp

Mục **B. Bảng tự kiểm trước khi nộp** trong phụ lục là danh sách mười việc cần
rà, bám theo Rubric 2 của học phần, tức phần chiếm 80% điểm. Đi hết danh sách
đó trước khi in quyển.

## 10. Nguồn gốc

Khung tài liệu chuyển thể từ mẫu đồ án của Trường Đại học Nha Trang
(github.com/nd-hung/thesis-template, tác giả TS. Nguyễn Đình Hưng). Phần được
giữ lại gồm bộ lệnh khai báo thông tin, các môi trường lời cam đoan, lời cảm
ơn, tóm tắt, và cách tổ chức thư mục. Phần được thay gồm toàn bộ nhận diện,
phông chữ, bảng màu, trang bìa, cấu trúc chương theo học phần AIP202, và gói
chèn mã nguồn đổi từ `minted` sang `listings` để không phải bật `-shell-escape`.
