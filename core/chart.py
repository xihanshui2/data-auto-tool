def get_recommended_charts_native(meta):
    """基于元数据提供图表推荐，无需拉取数据。"""
    recs =[]
    num_cols  = meta["num_cols"]
    cat_cols  = meta["cat_cols"]
    date_cols = meta["date_cols"]

    if date_cols and num_cols:
        recs.append({"type":"line","x":date_cols[0],"y":num_cols[0],
                     "color": cat_cols[0] if cat_cols else None,
                     "label":f"📈 {num_cols[0]} 的时间趋势"})
    if num_cols:
        recs.append({"type":"histogram","col":num_cols[0],
                     "label":f"📊 {num_cols[0]} 的分布"})
    if cat_cols and num_cols and not date_cols:
        recs.append({"type":"bar","x":cat_cols[0],"y":num_cols[0],
                     "label":f"🏷️ 按 {cat_cols[0]} 平均的 {num_cols[0]}"})
    if len(num_cols) >= 2:
        recs.append({"type":"scatter","x":num_cols[0],"y":num_cols[1],
                     "label":f"🔵 {num_cols[0]} 与 {num_cols[1]}"})
    return recs[:2]

PLOT_LAYOUT = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0d1828", font_family="Sora")
