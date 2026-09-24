---
title: News Updates
layout: post
author: Danishjeet Singh
---

<div class="news-list" markdown="1">

{% for year in site.data.news %}
  {% assign year_name = year[0] %}
  {% assign year_items = year[1] %}
  
## {{ year_name }}

  {% for item in year_items %}
**{{ item.date }}** {{ item.content | markdownify | remove: '<p>' | remove: '</p>' | strip }}

  {% endfor %}
{% endfor %}

</div>

[Back to home](/)