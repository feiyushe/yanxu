---
layout: default
title: 言叙·文章列表
---

# 🗂 言叙·文章列表

{% for file in site.static_files %}
{% if file.path contains 'articles/' and file.extname == '.md' %}
- [{{ file.basename }}]({{ site.baseurl }}{{ file.path }})
{% endif %}
{% endfor %}
