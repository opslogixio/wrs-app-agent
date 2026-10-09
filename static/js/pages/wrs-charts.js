
    var options = {
        chart: { height: 350, type: "bar", toolbar: { show: !1 } },
        plotOptions: {
          bar: { horizontal: !1, columnWidth: "45%", endingShape: "rounded" },
        },
        dataLabels: { enabled: !1 },
        stroke: { show: !0, width: 2, colors: ["transparent"] },
        series: [
          { name: "Repair", data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
          { name: "Maintenance", data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
          { name: "PDI", data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
          { name: "Recall", data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
          { name: "Other", data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ],
        colors: ["#34c38f", "#556ee6", "#f46a6a", "#F1B44C", "#50A5F1"],
        xaxis: {
          categories: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        },
        yaxis: { title: { text: "$ (thousands)", style: { fontWeight: "500" } } },
        grid: { borderColor: "#f1f1f1" },
        fill: { opacity: 1 },
        tooltip: {
          y: {
            formatter: function (e) {
              return "$ " + e + " thousands";
            },
          },
        },
      };

      (chart = new ApexCharts(
        document.querySelector("#column_chart"),
        options
      )).render();
      
