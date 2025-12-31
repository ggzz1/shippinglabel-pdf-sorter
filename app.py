import streamlit as st
from pypdf import PdfReader, PdfWriter
import re
import io
import zipfile
import numpy as np
from pdf2image import convert_from_bytes
import easyocr

# 1. 核心数据库
STATE_CODES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR"]
SENDER_ZIPS = {"92841", "91710", "91761", "91708", "30126", "90601"}

st.set_page_config(page_title="快递单专家 V18", layout="wide")
st.title("📦 快递单精准分类 - V18.0 OCR 强制修复版")

@st.cache_resource
def get_ocr_reader():
    # 首次加载模型需要时间，请耐心等待
    return easyocr.Reader(['en'])

def extract_state_logic(text):
    """核心识别逻辑：排除发件人，抓取最后一个有效州"""
    # 清理文本，处理可能的空格干扰 (如 T X 7 5 5 5 9)
    clean = " ".join(text.split()).upper()
    # 匹配 [2位州名] + [空格/符号] + [5位邮编]
    matches = re.findall(r'([A-Z]{2})\s*[^A-Z0-9]*\s*(\d{5})', clean)
    if matches:
        # 过滤发件人并取最后一个
        valid = [m[0] for m in matches if m[1] not in SENDER_ZIPS and m[0] in STATE_CODES]
        if valid: return valid[-1]
    return None

# --- UI 逻辑 ---
uploaded_file = st.file_uploader("上传 1229 或 800票 PDF", type="pdf")

if uploaded_file:
    file_bytes = uploaded_file.getvalue()
    
    # 步骤 1：快速文本分析
    if 'data' not in st.session_state:
        reader = PdfReader(io.BytesIO(file_bytes))
        results = []
        for i, page in enumerate(reader.pages):
            raw_text = page.extract_text() or ""
            state = extract_state_logic(raw_text)
            # 如果文字太短，直接视为失败，等待 OCR
            is_weak = len(raw_text.strip()) < 20
            results.append({
                "page": i,
                "state": state if not is_weak else None,
                "raw": raw_text,
                "method": "Text"
            })
        st.session_state.data = results

    # 结果统计
    identified = [r for r in st.session_state.data if r["state"]]
    failed = [r for r in st.session_state.data if not r["state"]]

    st.success(f"⚡ 快速分析完成！识别: {len(identified)} 页 | 待处理: {len(failed)} 页")

    # 步骤 2：OCR 补扫
    if failed:
        st.warning(f"有 {len(failed)} 页单子无法通过文本层读取（可能是扫描件或乱码层）。")
        if st.button("🚀 强制启动 OCR 补扫 (解决 Unknown 问题)"):
            ocr_reader = get_ocr_reader()
            progress = st.progress(0)
            
            for idx, item in enumerate(failed):
                try:
                    # 将该页转为图片
                    img_list = convert_from_bytes(file_bytes, first_page=item["page"]+1, last_page=item["page"]+1)
                    if img_list:
                        img_array = np.array(img_list[0])
                        ocr_text = " ".join(ocr_reader.readtext(img_array, detail=0))
                        new_state = extract_state_logic(ocr_text)
                        
                        # 更新全局状态
                        st.session_state.data[item["page"]]["state"] = new_state
                        st.session_state.data[item["page"]]["method"] = "OCR"
                except Exception as e:
                    st.error(f"第 {item['page']+1} 页 OCR 出错: {e}")
                
                progress.progress((idx + 1) / len(failed))
            st.rerun()

    # 步骤 3：最终分类下载
    if identified:
        st.divider()
        state_map = {}
        for r in st.session_state.data:
            if r["state"]:
                state_map.setdefault(r["state"], []).append(r["page"])

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            reader = PdfReader(io.BytesIO(file_bytes))
            for st_name, idxs in state_map.items():
                writer = PdfWriter()
                for idx in idxs: writer.add_page(reader.pages[idx])
                out = io.BytesIO(); writer.write(out)
                zf.writestr(f"{st_name}.pdf", out.getvalue())
        
        st.download_button("📥 下载最终分类包 (ZIP)", zip_buf.getvalue(), "Sorted_V18_Final.zip", use_container_width=True)

        # 诊断报告
        with st.expander("查看识别明细表"):
            st.table([{"页码": r["page"]+1, "识别结果": r["state"] or "❌ 失败", "识别方式": r["method"]} for r in st.session_state.data])
